"""API error model and Flask error handlers."""
from __future__ import annotations

from typing import Any, Optional

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from app.responses import build_meta


class ApiError(Exception):
    """Domain-level error carrying an HTTP status and a stable error_id."""

    def __init__(self, error_id: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Centralised catalogue of (error_id -> http_status) for convenience.
ERROR_HTTP: dict[str, int] = {
    "ERR_AUTH_REQUIRED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_SEGREGATION_VIOLATION": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_REQUEST_ALREADY_DECIDED": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_LIMIT_BREACH": 409,
    "ERR_COUNTERPARTY_LIMIT_BREACH": 409,
    "ERR_COUNTERPARTY_WATCHLIST": 409,
    "ERR_TRADER_SUSPENDED": 409,
    "ERR_EXPIRES_IN_PAST": 422,
    "ERR_INVALID_PAIR_FORMAT": 422,
    "ERR_INVALID_PAGINATION": 422,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_STOPLOSS_MODE": 422,
    # 200 is a *success* code on idempotent replay; never raised as an error.
    "ERR_IDEMPOTENCY_REPLAY": 200,
}


def make_error(error_id: str, message: Optional[str] = None) -> ApiError:
    http = ERROR_HTTP.get(error_id, 500)
    return ApiError(error_id, message or _default_message(error_id), http)


def _default_message(error_id: str) -> str:
    return {
        "ERR_AUTH_REQUIRED": "Missing or empty X-User-ID / X-User-Role header.",
        "ERR_FORBIDDEN": "Role is not permitted for this endpoint.",
        "ERR_SEGREGATION_VIOLATION": "Segregation of duties: actor cannot perform this operation on their own resource.",
        "ERR_NOT_FOUND": "Resource not found.",
        "ERR_INVALID_STATE": "Target entity is not in a valid state for the requested transition.",
        "ERR_REQUEST_ALREADY_DECIDED": "Limit adjustment request has already been decided.",
        "ERR_VERSION_CONFLICT": "Provided version does not match the current entity version.",
        "ERR_LIMIT_BREACH": "Trade would breach the trader's effective limit.",
        "ERR_COUNTERPARTY_LIMIT_BREACH": "Trade would breach the counterparty credit limit.",
        "ERR_COUNTERPARTY_WATCHLIST": "Counterparty is on the watchlist.",
        "ERR_TRADER_SUSPENDED": "Trader is not active or counterparty is on watchlist.",
        "ERR_EXPIRES_IN_PAST": "expires_at must be strictly in the future.",
        "ERR_INVALID_PAIR_FORMAT": "Currency pair code does not match the required format.",
        "ERR_INVALID_PAGINATION": "limit must be in [1,100] and offset >= 0.",
        "ERR_VALIDATION": "Request body failed validation.",
        "ERR_INVALID_STOPLOSS_MODE": "rule_mode must be one of PRICE, LOSS_AMOUNT, LOSS_RATIO and threshold_value > 0.",
    }.get(error_id, "Internal error.")


def _error_body(err_id: str, message: str) -> dict[str, Any]:
    return {
        "meta": build_meta(),
        "response_type": "error",
        "data": {"error_id": err_id, "message": message},
    }


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        return jsonify(_error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def handle_404(exc):
        return jsonify(_error_body("ERR_NOT_FOUND", "Resource not found.")), 404

    @app.errorhandler(405)
    def handle_405(exc):
        return jsonify(_error_body("ERR_NOT_FOUND", "Method not allowed.")), 404

    @app.errorhandler(HTTPException)
    def handle_http(exc: HTTPException):
        return jsonify(_error_body("ERR_VALIDATION", exc.description or "Request error.")), exc.code or 500

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):
        # Last-resort guard — should never fire for normal request flows.
        app.logger.exception("unhandled error processing %s %s", request.method, request.path)
        return jsonify(_error_body("ERR_VALIDATION", "Internal server error.")), 500
