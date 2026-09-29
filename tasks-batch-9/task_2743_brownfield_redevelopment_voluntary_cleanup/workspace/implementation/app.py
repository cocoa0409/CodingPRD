"""Brownfield Redevelopment / Voluntary Cleanup API (Flask entry point).

The store is in-memory and starts completely empty on every boot: no entity is
seeded, preloaded or hardcoded here or in any imported module.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import register_blueprints


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_blueprints(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 405:
            return response.error_response(
                "ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405)
        if exc.code == 404:
            return response.error_response(
                "ERR_NOT_FOUND", "Resource not found.", 404)
        return response.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Invalid request.", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return response.error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
