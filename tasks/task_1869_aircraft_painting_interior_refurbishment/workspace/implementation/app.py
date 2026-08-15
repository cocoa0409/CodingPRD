"""Aircraft Completion API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). All state is in-memory; the store starts
empty on every boot (no seeding) so per-test-server restarts are clean.
"""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response
from routes import register_all


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_all(app, prefix="/completion")

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(400)
    def handle_400(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return error_response(
            ApiError(ERR_INVALID_REQUEST, 400, "Malformed request"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        app.logger.exception("unexpected error")
        return error_response(
            ApiError(ERR_INVALID_REQUEST, 400, "Malformed request"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
