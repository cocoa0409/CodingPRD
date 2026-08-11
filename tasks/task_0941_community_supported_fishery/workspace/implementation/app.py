"""Community-Supported Fishery API -- entry point.

Storage is in-memory only and nothing is seeded at startup: every boot begins
with an empty store and the logical clock at its declared default.
"""
import errno
import os
import socket
import sys
import threading
import time

from flask import Flask
from werkzeug.exceptions import HTTPException

import store
from constants import API_PREFIX
from envelope import error_response
from errors import ApiError
from routes import BLUEPRINTS

# One request is served at a time.  The server is threaded so that HTTP/1.1
# keep-alive connections cannot block one another, but every WSGI call is
# serialised through this lock so the in-memory store and the per-request
# version-bump ledger stay consistent.
_REQUEST_LOCK = threading.Lock()


class _SerializedApp:
    def __init__(self, wsgi_app):
        self._wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        with _REQUEST_LOCK:
            result = self._wsgi_app(environ, start_response)
            return list(result)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for bp in BLUEPRINTS:
        app.register_blueprint(bp, url_prefix=API_PREFIX)

    @app.before_request
    def _begin():
        store.begin_request()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        code = exc.code or 500
        mapping = {404: "ERR_NOT_FOUND", 405: "ERR_METHOD_NOT_ALLOWED"}
        return error_response(mapping.get(code, "ERR_VALIDATION"),
                              exc.description or "Request could not be handled.",
                              code)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return error_response("ERR_VALIDATION", "Unhandled server error: %s" % exc, 500)

    app.wsgi_app = _SerializedApp(app.wsgi_app)
    return app


app = create_app()

_LISTENER = None


def _bind(host, port):
    """Pre-bind the listening socket with a bounded EADDRINUSE retry.

    Per-test-server isolation kills and relaunches this process before every
    test, and the dying LISTEN socket races the new bind.  Letting Werkzeug do
    the bind means a sys.exit(1) and a spurious "could not be restarted"
    failure, so the socket is created here with SO_REUSEADDR and retried on a
    ceiling well inside the harness's readiness budget: 24 attempts a quarter
    second apart is 6 seconds, after which a genuinely occupied port fails fast
    instead of leaving an orphan squatting.
    """
    deadline_attempts = 24
    for attempt in range(deadline_attempts):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            sock.listen(128)
            return sock
        except OSError as exc:
            sock.close()
            if exc.errno != errno.EADDRINUSE:
                raise
            if attempt == deadline_attempts - 1:
                break
            time.sleep(0.25)
    sys.stderr.write("could not bind %s:%d within the retry ceiling\n" % (host, port))
    sys.exit(1)


def main():
    from werkzeug.serving import make_server

    global _LISTENER
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "10000"))
    _LISTENER = _bind(host, port)
    server = make_server(host, port, app, threaded=True, fd=_LISTENER.fileno())
    server.serve_forever()


if __name__ == "__main__":
    main()
