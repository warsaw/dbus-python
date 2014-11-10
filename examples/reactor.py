#!/usr/bin/env python3

"""The Reactor class helps communications with an asynchronous service.

Asynchronous services often implement signals which are used to inform clients
of status and events.  In order to react to and process these signal, the
client must enter a main loop to wait for those signals.  This can be tricky
and error prone.

You can use this class to set up an asynchronous call, and register interest
in a set of signals.  When those signals come in, you can associate callbacks
for processing the signals.  This class also supports timeouts for cases where
the service doesn't respond in a given amount of time.

Use it like this:

class MyReactor(Reactor):
    def __init__(self):
        super().__init__(dbus.SystemBus())
        self.signal_1 = []
        self.signal_2 = []
        self.react_to('MySignalOne')
        self.react_to('MySignalTwo')

    def _do_MySignalOne(self, signal, path, *args):
        self.signal_1.append(args)

    def _do_MySignalTwo(self, signal, path, *args):
        self.signal_2.append(args)
        self.quit()

Now, you can create an instance of MyReactor and run it like so:

    iface = get_service_interface_somehow()
    reactor = MyReactor()
    reactor.run(iface.DoSomeTask, timeout=300)
    print('MySignalOne receive count:', len(reactor.signal_1))

A few other notes:

* You can also explicitly schedule the asynchronous method to run by calling
  Reactor.schedule().

* Reactor.react_to() can take an optional iface_name and object_path arguments
  if you want to further narrow the signals it will react to.

* If the timeout expires without getting a signal whose handler calls
  Reactor.quit(), then Reactor.timed_out will be set to True and the reactor
  will quit.  No exception is raised in this case; it's up to you to raise one
  if you want.

* Your subclass can implement a method called _default() if you want to catch
  any other signals not explicitly handled.

* Use _reset_timeout() if you want to boost the timeout period.

* You must call `DBusGMainLoop(set_as_default=True)` before using this class.
"""

from gi.repository import GLib


class Reactor:
    """A reactor base class for DBus signals."""

    def __init__(self, bus):
        self._bus = bus
        self._loop = None
        # Keep track of the GLib handles to the loop-quitting callback, and
        # all the signal matching callbacks.  Once the reactor run loop quits,
        # we want to remove all callbacks so they can't accidentally be called
        # again later.
        self._quitter = None
        self._signal_matches = []
        self._active_timeout = None
        self.timeout = 60
        self.timed_out = False

    def _handle_signal(self, *args, **kws):
        # We've seen some activity from the D-Bus service, so reset our
        # timeout loop.
        self._reset_timeout()
        # Now dispatch the signal.
        signal = kws.pop('member')
        path = kws.pop('path')
        method = getattr(self, '_do_' + signal, None)
        if method is None:
            # See if there's a default catch all.
            method = getattr(self, '_default', None)
        if method is not None:                          # pragma: no cover
            method(signal, path, *args, **kws)

    def _reset_timeout(self, *, try_again=True):
        if self._quitter is not None:
            GLib.source_remove(self._quitter)
            self._quitter = None
        if try_again:
            self._quitter = GLib.timeout_add_seconds(
                self._active_timeout, self._quit_with_error)

    def react_to(self, signal, iface_name=None, object_path=None):
        kws = dict(signal_name=signal,
                   member_keyword='member',
                   path_keyword='path')
        if iface_name is not None:
            kws['dbus_interface'] = iface_name
        if object_path is not None:
            kws['path'] = object_path
        signal_match = self._bus.add_signal_receiver(
            self._handle_signal, **kws)
        self._signal_matches.append(signal_match)

    def schedule(self, method, milliseconds=50):
        GLib.timeout_add(milliseconds, method)

    def run(self, method=None, timeout=None):
        if method is not None:
            self.schedule(method)
        self._active_timeout = (self.timeout if timeout is None else timeout)
        self._loop = GLib.MainLoop()
        self._reset_timeout()
        self._loop.run()

    def quit(self):
        self._loop.quit()
        for match in self._signal_matches:
            match.remove()
        del self._signal_matches[:]
        self._reset_timeout(try_again=False)
        self._quitter = None
        self._active_timeout = None

    def _quit_with_error(self):
        self.timed_out = True
        self.quit()
