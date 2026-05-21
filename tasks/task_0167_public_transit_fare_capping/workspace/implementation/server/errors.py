"""Error definitions and Flask error handlers."""
from __future__ import annotations

from flask import Flask, jsonify

from .response import error_envelope


# Error code -> HTTP status mapping. Sourced from §1.6 / §5.
ERROR_HTTP_STATUS = {
    "ERR_AUTH_MISSING": 401,
    "ERR_AUTH_INVALID_ROLE": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_CARD_NOT_ACTIVE": 409,
    "ERR_TRIP_ALREADY_OPEN": 409,
    "ERR_DUPLICATE_TAP": 409,
    "ERR_CARD_OUTSIDE_VALIDITY": 422,
    "ERR_TAP_OUT_NOT_AFTER_TAP_IN": 422,
    "ERR_MISSING_REDUCED_FARE_CERTIFICATE": 409,
    "ERR_MISSING_LOW_INCOME_VERIFICATION": 409,
    "ERR_CERTIFICATE_WINDOW_OVERLAP": 409,
    "ERR_DEVICE_ALREADY_BOUND": 409,
    "ERR_INVALID_AMOUNT": 422,
    "ERR_FSA_MONTHLY_CAP_EXCEEDED": 409,
    "ERR_INSUFFICIENT_FUNDS": 402,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_INVALID_PAGINATION": 422,
    "ERR_VALIDATION": 422,
}


class ApiError(Exception):
    """Raised to signal a structured API error with envelope semantics."""

    def __init__(self, error_id: str, message: str = "", http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status if http_status is not None else ERROR_HTTP_STATUS.get(error_id, 400)


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError):
        body = error_envelope(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def _not_found(_):
        body = error_envelope("ERR_NOT_FOUND", "Resource not found")
        return jsonify(body), 404

    @app.errorhandler(405)
    def _method_not_allowed(_):
        body = error_envelope("ERR_NOT_FOUND", "Method not allowed")
        return jsonify(body), 404

    @app.errorhandler(400)
    def _bad_request(_):
        body = error_envelope("ERR_VALIDATION", "Bad request")
        return jsonify(body), 422

    @app.errorhandler(Exception)
    def _generic(exc):
        # Surface unexpected exceptions with a consistent envelope (helps tests show useful info).
        body = error_envelope("ERR_INTERNAL", f"{type(exc).__name__}: {exc}")
        return jsonify(body), 500
