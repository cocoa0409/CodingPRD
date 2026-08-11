#!/usr/bin/env python3
"""Entry point.

Boot order is deliberate.  The runner SIGKILLs the previous server and
immediately re-launches this script on the same port, so two races are
possible: (i) the dying socket still holds the port, and (ii) the kernel
hands the port out as an ephemeral port during the kill->bind gap.  Both are
mitigated by shrinking the window: cheap module-presence checks first, our own
SO_REUSEADDR socket bound in a bounded retry loop next, and only then the
expensive Flask import / app construction.  Werkzeug then serves on the
already-bound descriptor instead of binding a second time.
"""

import importlib.util
import os
import socket
import sys
import time

_LISTEN_SOCKET = None  # module-level ref: keep the fd alive for the process


def _fail(message):
    sys.stderr.write("startup error: %s\n" % message)
    sys.stderr.flush()
    sys.exit(1)


def _bind(host, port, attempts=100, delay=0.05):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    last = None
    for _ in range(attempts):
        try:
            sock.bind((host, port))
            return sock
        except OSError as exc:
            last = exc
            time.sleep(delay)
    try:
        sock.close()
    except OSError:
        pass
    _fail("could not bind %s:%s after %d attempts (%s)" % (host, port, attempts, last))


def main():
    global _LISTEN_SOCKET

    for module_name in ("flask", "werkzeug"):
        if importlib.util.find_spec(module_name) is None:
            _fail("missing dependency: %s" % module_name)

    host = "0.0.0.0"
    try:
        port = int(os.environ.get("PORT", "10000"))
    except ValueError:
        port = 10000

    sock = _bind(host, port)
    sock.listen(512)
    sock.setblocking(True)
    _LISTEN_SOCKET = sock

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from werkzeug.serving import make_server

    from kb.app_factory import create_app

    server = make_server(host, port, create_app(), threaded=True, fd=sock.fileno())
    server.serve_forever()


if __name__ == "__main__":
    main()
