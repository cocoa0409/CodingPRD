"""Export Control & Sanctions Compliance API — Flask entry point."""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION
from response import error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(ApiError(ERR_NOT_FOUND, "Resource not found", 404))

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(ApiError(ERR_NOT_FOUND, "Resource not found", 404))

    @app.errorhandler(400)
    def handle_bad_request(err):
        return error_response(ApiError(ERR_VALIDATION, "Malformed request", 400))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return error_response(ApiError("ERR_INTERNAL", "Internal server error", 500))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
