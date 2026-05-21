"""Structured error class plus Flask error handlers (PRD §5 / SCAFFOLD §1.6)."""
from __future__ import annotations

from flask import Flask, jsonify

from .response import error_envelope


# Error id -> HTTP status. Sourced verbatim from §1.6 / §5.
ERROR_HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_LOA_EXCEEDS_SLIP": 422,
    "ERR_BEAM_BUFFER_VIOLATION": 422,
    "ERR_DRAFT_EXCEEDS_DEPTH": 422,
    "ERR_INSURANCE_LAPSED": 422,
    "ERR_LIVEABOARD_POLICY_VIOLATION": 422,
    "ERR_LIVEABOARD_QUOTA_EXCEEDED": 409,
    "ERR_SLIP_OCCUPIED": 409,
    "ERR_PUMP_OUT_CONFLICT": 409,
    "ERR_INVALID_DATE_RANGE": 422,
    "ERR_HAS_DEPENDENCIES": 409,
    "ERR_TOW_DEST_UNAVAILABLE": 422,
    "ERR_BAD_REQUEST": 400,
}


class ApiError(Exception):
    """Raised to signal a structured API error following the envelope."""

    def __init__(self, error_id: str, message: str = "", http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        if http_status is not None:
            self.http_status = http_status
        else:
            self.http_status = ERROR_HTTP_STATUS.get(error_id, 400)


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
        body = error_envelope("ERR_BAD_REQUEST", "Bad request")
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def _generic(exc):
        body = error_envelope("ERR_BAD_REQUEST", f"{type(exc).__name__}: {exc}")
        return jsonify(body), 500
