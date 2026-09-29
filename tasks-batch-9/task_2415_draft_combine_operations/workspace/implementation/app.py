"""Draft & Combine Operations API.

Flask application factory plus the request pipeline. Storage is entirely
in-memory (see db.py); nothing is persisted and no entity is ever seeded, so a
fresh process starts with an empty store and the logical clock at
2026-08-01T00:00:00Z.
"""

import os

from flask import Flask, g, request
from werkzeug.exceptions import HTTPException

import response
import routes
import versioning
from db import db
from errors import ApiError

MUTATING = ("POST", "PUT", "PATCH", "DELETE")


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    routes.register(app)

    @app.before_request
    def _open_request():
        db.lock.acquire()
        g._db_locked = True
        if request.method in MUTATING:
            versioning.snapshot()

    @app.teardown_request
    def _close_request(_exc=None):
        if getattr(g, "_db_locked", False):
            g._db_locked = False
            try:
                db.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return response.error(
                "ERR_INVALID_REQUEST", "The request could not be parsed.", 400
            )
        if exc.code in (404, 405):
            return response.error(
                "ERR_RESOURCE_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if exc.code == 401:
            return response.error(
                "ERR_UNAUTHENTICATED", "Authentication headers are required.", 401
            )
        return response.error(
            "ERR_INVALID_REQUEST", exc.description or "Request rejected.", exc.code or 400
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return response.error("ERR_INVALID_REQUEST", "Unhandled server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
