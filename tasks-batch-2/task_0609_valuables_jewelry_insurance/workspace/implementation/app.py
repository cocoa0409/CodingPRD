"""Valuables & Jewelry Insurance API — entry point.

In-memory only. State is wiped on every fresh boot; nothing is seeded.
"""
import os

from flask import Flask

import response
from errors import ApiError
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        return response.error("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return response.error("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return response.error(exc.error_id, exc.message, exc.http_status)
        return response.error("ERR_INVALID_REQUEST", "Unexpected error: %s" % exc, 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
