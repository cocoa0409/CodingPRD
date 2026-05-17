"""Mortgage Origination API — entry point."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response as resp
from errors import AppError, ERR_VALIDATION


def create_app() -> Flask:
    app = Flask(__name__)
    # Disable Flask's default JSON-error response so our envelope wins on bad bodies, etc.
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.errorhandler(AppError)
    def _handle_app_error(e: AppError):
        return resp.error(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _handle_404(e):
        return resp.error("ERR_RESOURCE_NOT_FOUND", "Route not found.", 404)

    @app.errorhandler(405)
    def _handle_405(e):
        return resp.error(ERR_VALIDATION, "Method not allowed.", 405)

    @app.errorhandler(HTTPException)
    def _handle_http(e: HTTPException):  # pragma: no cover
        return resp.error(
            ERR_VALIDATION, e.description or "Bad request.", e.code or 400
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(e: Exception):  # pragma: no cover
        return resp.error("ERR_INTERNAL", str(e), 500)

    from routes import register_routes
    register_routes(app)
    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
