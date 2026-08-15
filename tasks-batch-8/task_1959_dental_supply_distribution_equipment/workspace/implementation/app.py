"""Dental Supply Distribution & Equipment Service API — entry point."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 400:
            return envelope.error("ERR_INVALID_REQUEST", "Bad request", 400)
        return envelope.error("ERR_RESOURCE_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        import traceback

        traceback.print_exc()
        return envelope.error("ERR_INVALID_REQUEST", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
    )
