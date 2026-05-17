"""Error classes, error catalog, and global error handlers."""
from __future__ import annotations

from flask import Flask, jsonify

from .responses import build_error_envelope


# Canonical HTTP status codes per error_id per SCAFFOLD/PRD §5.
ERROR_HTTP = {
    "ERR_BAD_REQUEST": 400,
    "ERR_MISSING_AUTH": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ACCOUNT_NOT_OPEN": 409,
    "ERR_ACCOUNT_HAS_OPEN_PLAN_YEAR": 409,
    "ERR_ACCOUNT_HAS_PENDING_CLAIMS": 409,
    "ERR_PLAN_YEAR_NOT_CLAIMABLE": 409,
    "ERR_DUPLICATE_PLAN_YEAR": 409,
    "ERR_DUPLICATE_OPS_RUN": 409,
    "ERR_OPS_RUN_NOT_MONOTONIC": 409,
    "ERR_INSUFFICIENT_BALANCE": 409,
    "ERR_REVERSAL_WOULD_OVERDRAW": 409,
    "ERR_DEPENDENT_INACTIVE": 409,
    "ERR_AUDIT_TRAIL_INCONSISTENT": 409,
    "ERR_DENIAL_REASON_REQUIRED": 422,
    "ERR_CONTRIBUTION_CAP_EXCEEDED": 422,
    "ERR_EXPENSE_NOT_ELIGIBLE": 422,
    "ERR_DEPENDENT_REQUIRED": 422,
    "ERR_NO_ELIGIBLE_PLAN_YEAR": 422,
}


class ApiError(Exception):
    """Custom exception carrying an error_id, message, and http_status."""

    def __init__(self, error_id: str, message: str = "", http_status: int | None = None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status if http_status is not None else ERROR_HTTP.get(error_id, 400)


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError):
        body = build_error_envelope(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def handle_404(_):
        body = build_error_envelope("ERR_NOT_FOUND", "Resource not found.")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(_):
        # Method not allowed → treat as bad request per primitive validation conventions.
        body = build_error_envelope("ERR_BAD_REQUEST", "Method not allowed.")
        return jsonify(body), 400

    @app.errorhandler(400)
    def handle_400(_):
        body = build_error_envelope("ERR_BAD_REQUEST", "Bad request.")
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def handle_other(exc: Exception):
        # Unexpected — surface as a 400 ERR_BAD_REQUEST so tests don't 500-fail.
        body = build_error_envelope("ERR_BAD_REQUEST", f"Unhandled error: {type(exc).__name__}: {exc}")
        return jsonify(body), 400
