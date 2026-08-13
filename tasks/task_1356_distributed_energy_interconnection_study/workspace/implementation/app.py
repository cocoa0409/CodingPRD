"""Entry point: Flask app, error handlers, route registration, request locking.

Boot order note: the listen socket is bound BEFORE importing Flask/Werkzeug
and the app modules. The harness restarts the server before every test (many
rounds concurrently on a busy host). Between the kill of the previous listener
and this process's bind, the kernel may hand the just-freed port to an
outbound localhost connection as its ephemeral source port; a bind then fails
with EADDRINUSE, and if that socket is a TIME_WAIT/client socket (no
SO_REUSEADDR on it) the port stays blocked for up to 60s — past the runner's
restart-poll window. Binding first (a few hundred ms before the framework
imports finish) shrinks the vulnerable window drastically; any residual
EADDRINUSE is retried briefly, which covers the common short-lived case.
"""
import errno
import os
import socket
import time


def _bind_with_retry(port):
    """Bind the listen socket ourselves, retrying transient EADDRINUSE.

    The socket is passed to Werkzeug via `fd`, bypassing its fatal
    bind-and-sys.exit path entirely.
    """
    deadline = time.monotonic() + 12.0
    while True:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
            sock.listen(128)
            sock.set_inheritable(True)
            return sock
        except OSError as exc:
            sock.close()
            if exc.errno != errno.EADDRINUSE or time.monotonic() >= deadline:
                raise
            time.sleep(0.1)


# Bound as early as possible — see module docstring.
_PORT = int(os.environ.get("PORT", "10000"))
if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
    _LISTEN_SOCK = _bind_with_retry(_PORT)

from flask import Flask
from werkzeug.serving import make_server

from errors import ApiError
from middleware import WRITE_LOCK
from response import err
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    register_routes(app)

    @app.before_request
    def _acquire_lock():
        # Serialize request handling so check-then-act sequences (OCC version
        # checks, deposit overpayment, milestone review) are atomic under the
        # threaded dev server.
        WRITE_LOCK.acquire()

    @app.teardown_request
    def _release_lock(exc=None):
        try:
            WRITE_LOCK.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return err("ERR_NOT_FOUND", 404, "Referenced resource does not exist")

    @app.errorhandler(405)
    def handle_405(e):
        return err("ERR_NOT_FOUND", 404, "Referenced resource does not exist")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return err("ERR_INTERNAL", 500, "Internal server error")

    return app


app = create_app()


def _serve(port):
    server = make_server("0.0.0.0", port, app, threaded=True,
                         fd=_LISTEN_SOCK.fileno())
    # Keep the socket object alive for the lifetime of the server.
    server._bound_sock = _LISTEN_SOCK
    server.serve_forever()


if __name__ == "__main__":
    _serve(_PORT)
