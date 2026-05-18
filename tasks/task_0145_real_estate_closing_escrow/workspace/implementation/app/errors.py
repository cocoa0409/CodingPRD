"""Custom exception class and Flask error handlers for the API."""
from __future__ import annotations

from typing import Any, Dict

from flask import Flask, jsonify, request

from app.envelope import error_envelope


# Canonical error catalog (id -> http status)
ERRORS: Dict[str, int] = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_BENEFICIARY_KIND_MISMATCH": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_CROSS_ENTITY_STATE": 409,
    "ERR_SOD_VIOLATION": 403,
    "ERR_WIRE_CALLBACK_MISSING": 422,
    "ERR_CD_WAITING_PERIOD": 409,
    "ERR_1031_45DAY_LAPSED": 409,
    "ERR_1031_180DAY_LAPSED": 409,
    "ERR_1031_GAIN_INVARIANT": 422,
    "ERR_LENDERS_REQUIRES_OWNERS": 409,
    "ERR_TITLE_NOT_CLEARED": 409,
    "ERR_EMD_BELOW_FLOOR": 422,
    "ERR_EMD_SPLIT_INVARIANT": 422,
    "ERR_CCR_NOT_ACKNOWLEDGED": 409,
    "ERR_DISBURSEMENT_OVERDRAW": 422,
    "ERR_IDEMPOTENCY_REPLAY_MISMATCH": 409,
    "ERR_VERSION_MISMATCH": 409,
    "ERR_WIRE_LOCKED_BY_DISBURSEMENT": 409,
    "ERR_BAD_REQUEST": 400,
}


class ApiError(Exception):
    """Standard API error with an error_id and an HTTP status code."""

    def __init__(self, error_id: str, message: str = "", http_status: int | None = None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status if http_status is not None else ERRORS.get(error_id, 400)


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def _handle_api_error(err: ApiError):
        body = error_envelope(err.error_id, err.message)
        return jsonify(body), err.http_status

    @app.errorhandler(404)
    def _handle_404(_e: Any):
        body = error_envelope("ERR_NOT_FOUND", "Resource not found.")
        return jsonify(body), 404

    @app.errorhandler(405)
    def _handle_405(_e: Any):
        body = error_envelope("ERR_BAD_REQUEST", "Method not allowed.")
        return jsonify(body), 400

    @app.errorhandler(400)
    def _handle_400(_e: Any):
        body = error_envelope("ERR_BAD_REQUEST", "Bad request.")
        return jsonify(body), 400

    @app.errorhandler(415)
    def _handle_415(_e: Any):
        body = error_envelope("ERR_BAD_REQUEST", "Unsupported media type.")
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def _handle_unknown(err: Exception):
        # Last-resort safety net: never expose internals.
        body = error_envelope("ERR_BAD_REQUEST", f"Internal error: {type(err).__name__}")
        return jsonify(body), 400
