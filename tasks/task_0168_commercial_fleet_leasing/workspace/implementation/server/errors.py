"""ApiError class and Flask handlers — error codes sourced from §1.6 / §5."""
from __future__ import annotations

from flask import Flask, jsonify

from .response import error_envelope


ERROR_HTTP_STATUS = {
    "ERR_AUTH_REQUIRED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_VALIDATION": 422,
    "ERR_VEHICLE_ALREADY_ALLOCATED": 409,
    "ERR_OPEN_COLLISION_BLOCKS_RETURN": 409,
    "ERR_CARD_INACTIVE": 409,
    "ERR_QUARTER_CLOSED": 409,
    "ERR_QUARTER_NOT_READY": 409,
    "ERR_REVISION_LIMIT_REACHED": 422,
    "ERR_CARD_LIMIT_EXCEEDED": 422,
    "ERR_DISPUTE_WINDOW_CLOSED": 409,
    "ERR_DUPLICATE_SETTLEMENT_PERIOD": 409,
    "ERR_ACTUAL_COST_REQUIRED": 422,
    "ERR_VEHICLE_NOT_RETURNABLE": 409,
}


class ApiError(Exception):
    """Structured API error carrying error_id, message, and an HTTP status."""

    def __init__(self, error_id: str, message: str = "", http_status: int | None = None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = (
            http_status
            if http_status is not None
            else ERROR_HTTP_STATUS.get(error_id, 400)
        )


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError):
        return jsonify(error_envelope(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def _not_found(_):
        return jsonify(error_envelope("ERR_NOT_FOUND", "Resource not found")), 404

    @app.errorhandler(405)
    def _method_not_allowed(_):
        return jsonify(error_envelope("ERR_NOT_FOUND", "Method not allowed")), 404

    @app.errorhandler(400)
    def _bad_request(_):
        return jsonify(error_envelope("ERR_VALIDATION", "Bad request")), 422

    @app.errorhandler(Exception)
    def _generic(exc):
        return (
            jsonify(error_envelope("ERR_INTERNAL", f"{type(exc).__name__}: {exc}")),
            500,
        )
