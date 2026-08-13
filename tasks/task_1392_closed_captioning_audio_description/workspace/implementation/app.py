"""Entry point: Flask app, error handlers, route registration.

Listens on the PORT env var (default 10000), bound to 0.0.0.0.
"""
import os
import traceback

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from respond import error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    register_routes(app)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _handle_404(_err):
        return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(405)
    def _handle_405(_err):
        return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        traceback.print_exc()
        return error_response(ApiError("ERR_INTERNAL", 500, f"Internal error: {err}"))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
