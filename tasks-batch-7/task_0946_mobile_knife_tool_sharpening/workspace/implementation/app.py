#!/usr/bin/env python3
"""Entry point.

Boot latency is a correctness property here: the test harness kills the server
with SIGKILL and immediately re-launches it, and between that kill and our
bind() a co-tenant process's outbound connect() can steal the exact port number
(an ephemeral-port steal).  The defence is to make the kill->bind window as
small as possible rather than to lengthen a retry ceiling, so:

  * module-scope imports here are stdlib only;
  * claiming the listening socket is the very first act of main(), before Flask
    or any application module is imported;
  * the already-bound socket is then handed to werkzeug via `fd=`;
  * a bounded retry (280 attempts at 50 ms, about 14 s) sits just inside the
    harness's readiness budget so a transient steal is ridden out rather than
    surrendered to.
"""

import os
import socket
import sys
import time

BIND_ATTEMPTS = 280
BIND_RETRY_SECONDS = 0.05
BACKLOG = 128


def claim_socket(host, port):
    """Bind the listening socket, retrying briefly while the port is taken."""
    last = None
    for _ in range(BIND_ATTEMPTS):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            sock.listen(BACKLOG)
            sock.setblocking(True)
            return sock
        except OSError as exc:
            last = exc
            sock.close()
            time.sleep(BIND_RETRY_SECONDS)
    raise SystemExit("could not bind %s:%s (%s)" % (host, port, last))


def main():
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "10000"))
    started = time.time()
    sock = claim_socket(host, port)
    bound_ms = (time.time() - started) * 1000.0

    from werkzeug.serving import make_server

    from app_factory import create_app

    application = create_app()
    server = make_server(host, port, application, threaded=True, fd=sock.fileno())
    sys.stderr.write("listening on %s:%d (pre-bind %.1f ms)\n" % (host, port, bound_ms))
    sys.stderr.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
