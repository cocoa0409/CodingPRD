"""Custom exception type and Flask error-handler registration."""
from __future__ import annotations

from typing import Any

from flask import Flask, jsonify

from .response import error_envelope


# Mapping of error_id -> http status (per scaffold §1.6 / PRD §5)
ERROR_HTTP_STATUS: dict[str, int] = {
    "ERR_UNAUTHORIZED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_PRICING_PROFILE_NOT_FOUND": 404,
    "ERR_BAD_REQUEST": 422,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_COMPARTMENT_FAULT": 409,
    "ERR_COMPARTMENT_UNAVAILABLE": 409,
    "ERR_CABINET_OFFLINE": 409,
    "ERR_INVALID_INSURANCE": 422,
    "ERR_RENEWAL_NOT_PERMITTED": 409,
    "ERR_CLAIM_ALREADY_OPEN": 409,
    "ERR_CLAIM_WINDOW_EXPIRED": 409,
    "ERR_REFUND_BLOCKED_BY_CLAIM": 409,
    "ERR_PAYOUT_EXCEEDS_CAP": 422,
    "ERR_DUPLICATE_PROFILE": 409,
    "ERR_DUPLICATE_SLOT": 409,
}


class ApiError(Exception):
    """Raised anywhere in the codebase to propagate a structured error response."""

    def __init__(self, error_id: str, message: str | None = None, http_status: int | None = None) -> None:
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status if http_status is not None else ERROR_HTTP_STATUS.get(error_id, 422)
        super().__init__(f"{error_id}: {self.message}")


def _default_message(error_id: str) -> str:
    return error_id.replace("ERR_", "").replace("_", " ").lower().capitalize() + "."


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError) -> Any:
        body = error_envelope(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def _handle_404(_exc):
        body = error_envelope("ERR_NOT_FOUND", "Resource not found.")
        return jsonify(body), 404

    @app.errorhandler(405)
    def _handle_405(_exc):
        body = error_envelope("ERR_NOT_FOUND", "Method not allowed.")
        return jsonify(body), 404

    @app.errorhandler(400)
    def _handle_400(_exc):
        body = error_envelope("ERR_BAD_REQUEST", "Bad request.")
        return jsonify(body), 422

    @app.errorhandler(Exception)
    def _handle_generic(exc):  # noqa: ANN001
        body = error_envelope("ERR_BAD_REQUEST", f"Unhandled error: {exc.__class__.__name__}: {exc}")
        return jsonify(body), 500
