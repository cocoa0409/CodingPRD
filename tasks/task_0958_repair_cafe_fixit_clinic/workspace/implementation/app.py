"""Repair Café & Fix-It Clinic API — Flask entry point."""

import os

from flask import Flask, request

from errors import ApiError
from middleware import authenticate
from response import error_response
from routes import register_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _authenticate():
        # Priority 1 (auth) applies to every API endpoint.
        if request.path.startswith("/api"):
            authenticate()

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def _handle_404(_err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _handle_405(_err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        return error_response("ERR_INTERNAL", "Internal server error: %s" % err, 500)

    register_routes(app)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
