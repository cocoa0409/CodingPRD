"""Scholastic Chess League API — Flask entry point.

In-memory only storage (Python dicts). The store starts empty on every boot;
no seeding, no disk persistence.
"""
import os

from flask import Flask
from werkzeug.exceptions import NotFound, MethodNotAllowed

from errors import ApiError
from response import error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        app.logger.exception("unexpected error")
        return error_response(ApiError("ERR_INVALID_REQUEST", 400, str(err)))

    register_routes(app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
