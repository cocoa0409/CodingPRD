"""Entry point for the Adaptive & Inclusive Recreation API.

BOOT ROBUSTNESS
---------------
Intermittent "API server could not be restarted" failures under
``--isolation per-test-server`` have been root-caused as an *ephemeral-port
steal*: the harness allocates ``$PORT`` by binding port 0, so the number comes
out of the kernel ephemeral range 32768-60999.  In the window between the
harness's ``kill -9`` of the previous server and this process's ``bind()``, a
co-tenant's outbound ``connect()`` can take that exact number as its source
port and block a wildcard bind for the connection's lifetime.

The fix is to *shrink the kill -> bind window*, not to lengthen a retry
ceiling.  Therefore:

  * module-scope imports here are stdlib-only -- no Flask, no blueprints, no
    dependency probing;
  * claiming the listening socket is the very first act of ``main()``;
  * only then is the application imported and built;
  * the already-bound socket is handed to werkzeug via ``make_server(fd=...)``
    so there is never a second bind.
"""

import os
import socket
import sys
import time

_PROCESS_START = time.time()

BIND_ATTEMPTS = 280
BIND_SLEEP_SECONDS = 0.05


def claim_socket(port):
    """Bind and listen on 0.0.0.0:port, retrying a bounded number of times.

    ~280 attempts x 50 ms is about 14 s, which sits just inside the harness's
    15 s readiness budget rather than surrendering early.
    """
    last_error = None
    for _ in range(BIND_ATTEMPTS):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", port))
            sock.listen(128)
            return sock
        except OSError as exc:
            last_error = exc
            try:
                sock.close()
            except OSError:
                pass
            time.sleep(BIND_SLEEP_SECONDS)
    raise SystemExit("could not bind 0.0.0.0:%s (%s)" % (port, last_error))


def main():
    port = int(os.environ.get("PORT", "10000"))

    # --- FIRST ACT: claim the listening socket ------------------------------
    sock = claim_socket(port)
    elapsed_ms = (time.time() - _PROCESS_START) * 1000.0
    sys.stderr.write("[boot] bound 0.0.0.0:%d in %.1f ms\n" % (port, elapsed_ms))
    sys.stderr.flush()

    # --- only now pull in the framework and build the app ------------------
    from werkzeug.serving import make_server

    from application import create_app

    app = create_app()
    server = make_server("0.0.0.0", port, app, threaded=True, fd=sock.fileno())
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            sock.close()
        except OSError:
            pass


if __name__ == "__main__":
    main()
