"""Application error definitions and global error handlers."""
from __future__ import annotations

from flask import Flask, jsonify

from .responses import build_envelope, error_envelope


# -----------------------------------------------------------------------------
# Error catalog: error_id -> HTTP status code
# -----------------------------------------------------------------------------
ERROR_CATALOG = {
    "ERR_AUTH_HEADER_MISSING": 401,
    "ERR_AUTH_HEADER_INVALID": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_PROVIDER_SUSPENDED": 403,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_DOSE_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_ADVERSE_EVENT_NOT_FOUND": 404,
    "ERR_CERTIFICATE_NOT_FOUND": 404,
    "ERR_PROVIDER_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_LOT_RECALLED": 409,
    "ERR_LOT_EXHAUSTED": 409,
    "ERR_CERTIFICATE_DUPLICATE": 409,
    "ERR_VAERS_ALREADY_SUBMITTED": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_ALLERGY_CONTRAINDICATION": 422,
    "ERR_AGE_OUT_OF_RANGE": 422,
    "ERR_MIN_INTERVAL_VIOLATION": 422,
    "ERR_ADMIN_TIME_OUT_OF_RANGE": 422,
    "ERR_LOT_PRODUCT_MISMATCH": 422,
    "ERR_DOSE_PATIENT_MISMATCH": 422,
    "ERR_ONSET_OUT_OF_WINDOW": 422,
    "ERR_SOD_VIOLATION": 422,
    "ERR_VAERS_NOT_REPORTABLE": 422,
    "ERR_VALIDATION": 400,
}


class APIError(Exception):
    """Domain-level exception. Use raise APIError("ERR_XXX", "message")."""

    def __init__(self, error_id: str, message: str = ""):
        super().__init__(message or error_id)
        if error_id not in ERROR_CATALOG:
            raise ValueError(f"Unknown error_id {error_id!r}")
        self.error_id = error_id
        self.http_status = ERROR_CATALOG[error_id]
        self.message = message or error_id


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(APIError)
    def handle_api_error(exc: APIError):
        body = error_envelope(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def handle_404(_exc):
        # Unknown route -> generic validation-ish error. Tests don't directly
        # exercise this much, but we keep envelope structure consistent.
        body = error_envelope("ERR_VALIDATION", "Resource not found.")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(_exc):
        body = error_envelope("ERR_VALIDATION", "Method not allowed.")
        return jsonify(body), 405

    @app.errorhandler(400)
    def handle_400(exc):
        msg = str(exc) if exc else "Bad request."
        body = error_envelope("ERR_VALIDATION", msg)
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Last-resort safety net. Don't leak stack traces.
        body = error_envelope("ERR_VALIDATION", f"Internal error: {type(exc).__name__}")
        return jsonify(body), 500
