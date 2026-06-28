"""Ag Equipment Dealer API — Flask entry point.

In-memory only. No seeding at startup. Boots fresh on every invocation.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        # Unknown route -> ERR_NOT_FOUND envelope
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INVALID_REQUEST", str(exc), 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
