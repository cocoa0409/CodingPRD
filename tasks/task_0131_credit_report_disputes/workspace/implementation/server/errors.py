"""Exception class + Flask error-handler registration."""
from __future__ import annotations

from flask import Flask, request
from werkzeug.exceptions import HTTPException


class ApiError(Exception):
    """A business-logic error that maps to a structured API response."""

    def __init__(self, error_id: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def register_error_handlers(app: Flask) -> None:
    # Imports kept local to avoid circular references.
    from .responses import json_error

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return json_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        return json_error("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return json_error(
            "ERR_INVALID_REQUEST",
            f"Method {request.method} not allowed on {request.path}.",
            400,
        )

    @app.errorhandler(400)
    def handle_400(_exc):
        return json_error("ERR_INVALID_REQUEST", "Malformed request.", 400)

    @app.errorhandler(HTTPException)
    def handle_http_exc(exc: HTTPException):
        # Fall-back for any other werkzeug exception.
        return json_error(
            "ERR_INVALID_REQUEST",
            exc.description or "Invalid request.",
            exc.code or 400,
        )

    @app.errorhandler(Exception)
    def handle_unknown(exc: Exception):  # pragma: no cover - defensive
        app.logger.exception("Unhandled exception: %s", exc)
        return json_error("ERR_INVALID_REQUEST", "Internal error.", 500)
