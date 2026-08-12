"""Retail Construction Rollout API — entry point.

The store starts empty on every boot (no seeding); the logical clock reads
2026-05-01T00:00:00Z until a ProgramDirector sets it. Listens on $PORT
(default 10000), bound to 0.0.0.0.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import register_blueprints


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "resource not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return error_response(ApiError("ERR_NOT_FOUND", 405, "method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc)
        return error_response(ApiError("ERR_INTERNAL", 500, str(exc)))

    register_blueprints(app)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
