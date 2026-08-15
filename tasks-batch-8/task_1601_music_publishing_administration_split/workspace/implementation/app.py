"""Music Publishing Administration & Split Management API.

Flask entry point. Storage is fully in-memory (see db.py); every process
boot starts with an empty store and the logical clock at 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION
from response import error_response
from routes import ALL_BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(ApiError(ERR_NOT_FOUND, 404, "resource not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(
            ApiError(ERR_NOT_FOUND, 404, "resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(
            ApiError(ERR_VALIDATION, 500, "internal error: %s" % err))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
