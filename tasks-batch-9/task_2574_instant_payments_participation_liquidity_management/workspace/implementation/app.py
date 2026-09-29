"""Instant Payments Participation & Liquidity Management API."""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from db import db
from errors import ApiError, HTTP_STATUS
from response import error_response
from routes import register_blueprints


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    register_blueprints(app)

    @app.before_request
    def _acquire():
        # Single-writer semantics: the domain rules are full-store reads and
        # cascading writes, so one request at a time keeps them consistent.
        db.lock.acquire()
        g._store_locked = True

    @app.teardown_request
    def _release(exc=None):
        if getattr(g, "_store_locked", False):
            g._store_locked = False
            try:
                db.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return error_response(
            "ERR_INVALID_REQUEST",
            exc.description or "The request could not be processed.",
            exc.code or 400,
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    assert HTTP_STATUS
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
