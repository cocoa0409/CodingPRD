"""Ticket Access Control API -- Flask entry point.

State lives in process memory only (see db.py) and boots empty on every start,
so the per-test server isolation of the harness gives each test a clean slate.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import routes
from db import db
from errors import ApiError
from response import error


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    routes.register(app)

    @app.before_request
    def _acquire():
        # One writer at a time: the cascades touch several collections at once.
        db.lock.acquire()
        g._store_locked = True

    @app.teardown_request
    def _release(_exc=None):
        if getattr(g, "_store_locked", False):
            g._store_locked = False
            try:
                db.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error("ERR_NOT_FOUND", "The requested path does not exist.", 404)
        if exc.code == 405:
            return error(
                "ERR_METHOD_NOT_ALLOWED",
                "The HTTP method is not allowed for this path.",
                405,
            )
        if exc.code in (400, 415):
            return error("ERR_INVALID_REQUEST", "The request body could not be parsed.", 400)
        return error("ERR_INTERNAL", exc.description or "Request failed.", exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        app.logger.exception("unhandled error: %s", exc)
        return error("ERR_INTERNAL", "An unexpected server error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
