"""Entry point: Flask app wiring, error handlers, route registration."""

import os
from flask import Flask, request

from errors import ApiError, ERR_VALIDATION
from response import error_response
import routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    routes.register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(ERR_VALIDATION, "Route not found.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(ERR_VALIDATION, "Method not allowed.", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Never leak a stack trace; surface as a generic 500.
        return error_response(ERR_VALIDATION, f"Internal error: {err}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
