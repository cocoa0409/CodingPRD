"""Entry point.

The socket is bound as the very first thing this process does -- BEFORE any
heavy import -- so that the window between the previous per-test server being
killed and this one claiming the port is as small as possible.  Werkzeug calls
sys.exit(1) when its own bind fails, which surfaces as a spurious "server could
not be restarted" on an innocent test; binding ourselves with a bounded retry
loop and handing the already-bound socket to make_server() avoids that.
"""

import os
import socket
import sys
import time

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "10000"))


def _bind(host, port, budget_seconds=20.0):
    deadline = time.time() + budget_seconds
    delay = 0.02
    last = None
    while True:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            sock.listen(2048)
            sock.setblocking(False)
            return sock
        except OSError as exc:  # address in use / dying LISTEN socket
            last = exc
            try:
                sock.close()
            except OSError:
                pass
            if time.time() >= deadline:
                raise last
            time.sleep(delay)
            delay = min(delay * 1.5, 0.25)


_SOCK = _bind(HOST, PORT)

# Only now pull in the framework and the application modules.
from werkzeug.serving import make_server  # noqa: E402

from api import create_app  # noqa: E402


def main():
    app = create_app()
    srv = make_server(HOST, PORT, app, threaded=True, fd=_SOCK.fileno())
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
