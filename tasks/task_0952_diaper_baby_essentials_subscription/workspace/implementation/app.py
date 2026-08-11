"""Diaper & Baby-Essentials Subscription API.

Boots clean from a fresh process every time: all state lives in Python dicts in
`store.db` and NOTHING is seeded.
"""

import os
import socket
import sys
import time

from flask import Flask, request
from werkzeug.exceptions import HTTPException

import auth
import envelope
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes import BLUEPRINTS
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _authenticate():
        # Gate G1 runs for every request, including unmatched paths.
        auth.authenticate()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error_response(exc)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return envelope.error_response(
                ApiError("ERR_ACCOUNT_NOT_FOUND", "No route matches this path."))
        if exc.code == 405:
            return envelope.error_response(
                ApiError("ERR_FORBIDDEN_ROLE", "Method not allowed on this path."))
        return envelope.error_response(
            ApiError("ERR_INVALID_FORMAT", exc.description or "Bad request."))

    @app.errorhandler(Exception)
    def _unhandled(exc):
        app.logger.exception("unhandled error")
        return envelope.error_response(
            ApiError("ERR_INVALID_FORMAT", "Unhandled server error: %s" % exc))

    return app


app = create_app()


def _bind(host, port, attempts=40, delay=0.05):
    """Bounded pre-bind retry: the per-test reboot races the dying LISTEN socket,
    and Werkzeug would sys.exit(1) on a bind failure. Keep the kill-to-bind
    window as short as possible rather than lengthening any timeout."""
    last = None
    for _ in range(attempts):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            sock.listen(256)
            sock.setblocking(False)
            return sock
        except OSError as exc:
            last = exc
            try:
                sock.close()
            except OSError:
                pass
            time.sleep(delay)
    raise SystemExit("could not bind %s:%s (%s)" % (host, port, last))


def main():
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "10000"))
    sock = _bind(host, port)
    from werkzeug.serving import make_server
    server = make_server(host, port, app, threaded=True, fd=sock.fileno())
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
