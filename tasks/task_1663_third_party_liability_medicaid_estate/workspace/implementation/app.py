"""Entry point: Flask app, error handlers, route registration.

The store starts empty on every boot; nothing is seeded or preloaded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response
from routes import cases, clock, estates, liens, members, notices, postings, settlements, waivers


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (
        members,
        cases,
        liens,
        settlements,
        postings,
        estates,
        waivers,
        notices,
        clock,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_response(ERR_INVALID_REQUEST, "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        if isinstance(e, HTTPException):
            return error_response(ERR_INVALID_REQUEST, e.description, e.code)
        return error_response(ERR_INVALID_REQUEST, "Unexpected server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
    )
