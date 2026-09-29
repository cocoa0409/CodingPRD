"""Vote-By-Mail Processing API -- application entry point.

The service is mounted under /vote-by-mail. All state lives in process memory
and starts empty on every boot; nothing is seeded here or anywhere else.
"""
import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import db
import response
from errors import ApiError
from routes import (
    cures,
    elections,
    envelopes,
    mailing,
    misc,
    observers,
    remakes,
    requests as requests_routes,
    reviewers,
    reviews,
    voters,
)

PREFIX = "/vote-by-mail"

BLUEPRINTS = (
    elections.bp,
    voters.bp,
    reviewers.bp,
    requests_routes.bp,
    mailing.bp,
    envelopes.bp,
    reviews.bp,
    cures.bp,
    remakes.bp,
    observers.bp,
    misc.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=PREFIX)

    @app.before_request
    def _acquire():
        db.LOCK.acquire()
        g._store_locked = True

    @app.teardown_request
    def _release(exc=None):
        if getattr(g, "_store_locked", False):
            g._store_locked = False
            try:
                db.LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return response.error_response(
                "ERR_RECORD_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if exc.code == 405:
            return response.error_response(
                "ERR_INVALID_REQUEST",
                "The HTTP method is not allowed for this resource.",
                405,
            )
        if exc.code and 400 <= exc.code < 500:
            return response.error_response(
                "ERR_INVALID_REQUEST", exc.description or "Invalid request.", exc.code
            )
        return response.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return response.error_response(
            "ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )
