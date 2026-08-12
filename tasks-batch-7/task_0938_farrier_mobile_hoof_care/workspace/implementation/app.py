"""Farrier & Mobile Hoof-Care API -- application entry point."""

import errno
import os
import socket
import sys
import time

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from core.envelope import error_body
from core.errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes import register_blueprints

    register_blueprints(app)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return jsonify(error_body("ERR_VALIDATION", "Unknown resource path.")), 404
        if exc.code == 405:
            return jsonify(error_body("ERR_VALIDATION", "Method not allowed.")), 405
        return (
            jsonify(error_body("ERR_VALIDATION", exc.description or "Request could not be processed.")),
            exc.code or 400,
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error")
        return jsonify(error_body("ERR_VALIDATION", "Unexpected server error.")), 500

    return app


app = create_app()


def _bind(host, port):
    """Pre-bind the listening socket, tolerating a dying predecessor's socket.

    Under ``--isolation per-test-server`` the harness kill -9s the previous
    server and immediately spawns this one, so the port can still be held for a
    moment.  Werkzeug treats a bind failure as fatal (SystemExit), so the retry
    has to happen here -- and it is bounded at roughly six seconds so a rejected
    respawn dies instead of turning into an orphan that squats the port.
    """
    deadline_attempts = 24
    for attempt in range(deadline_attempts):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            sock.listen(128)
            sock.setblocking(True)
            return sock
        except OSError as exc:
            sock.close()
            if exc.errno != errno.EADDRINUSE:
                raise
            if attempt == deadline_attempts - 1:
                break
            time.sleep(0.25)
    sys.stderr.write("could not bind %s:%d - port still held\n" % (host, port))
    sys.exit(1)


def main():
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "10000"))
    sock = _bind(host, port)
    from werkzeug.serving import make_server

    server = make_server(host, port, app, threaded=True, fd=sock.fileno())
    server.serve_forever()


if __name__ == "__main__":
    main()
