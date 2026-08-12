"""Feed Mill Operations & Ration Formulation API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). Storage is in-memory only and starts
empty on every boot; nothing is seeded.
"""
import os

from flask import Flask

from envelope import JSONProvider, error_response
from errors import ApiError
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.json_provider_class = JSONProvider
    app.json = JSONProvider(app)
    register_routes(app)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _handle_404(_err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def _handle_405(_err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        app.logger.exception("Unhandled error: %s", err)
        return error_response(ApiError("ERR_INTERNAL", 500, "Internal server error"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
