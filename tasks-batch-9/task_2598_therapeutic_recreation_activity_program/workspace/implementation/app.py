"""Therapeutic Recreation Activity Program API (Flask, in-memory store).

The store boots completely empty: no entity is seeded, preloaded, registered
or hardcoded at startup. Every entity is created by a client call.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import (
    catalog,
    council,
    outings,
    participation,
    plans,
    residents,
    sessions,
    survey,
    volunteers,
)

API_PREFIX = "/recreation"

BLUEPRINTS = (
    residents.bp,
    catalog.bp,
    plans.bp,
    sessions.bp,
    participation.bp,
    volunteers.bp,
    outings.bp,
    council.bp,
    survey.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_METHOD_NOT_ALLOWED",
                "The HTTP method is not allowed for this path.",
                405,
            )
        if exc.code == 400:
            return error_response(
                "ERR_INVALID_REQUEST", "The request could not be parsed.", 400
            )
        return error_response(
            "ERR_INTERNAL", exc.description or "Request failed.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", "An unexpected error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
