"""Custom ApiError exception and Flask error handlers."""
from __future__ import annotations

from flask import Flask, jsonify

from .response import error_envelope


# Default HTTP status per error_id (§1.6, §5).
ERROR_HTTP_STATUS = {
    "ERR_UNAUTHORIZED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 422,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_EEO_DATA_MISSING": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_REFERRAL_REQUIRES_REFERRER": 422,
    "ERR_INTERVIEWER_DOUBLE_BOOKED": 409,
    "ERR_RECRUITER_REQUISITION_CAP": 409,
    "ERR_DUPLICATE_APPLICATION": 409,
    "ERR_NO_QUALIFYING_FEEDBACK": 409,
    "ERR_OFFER_EXCEEDS_REQ_BUDGET": 422,
    "ERR_MANAGER_BUDGET_EXCEEDED": 422,
    "ERR_HEADCOUNT_EXCEEDED": 409,
    "ERR_DIVERSITY_GOAL_NOT_MET": 422,
    "ERR_OFFER_EXPIRES_IN_PAST": 422,
    "ERR_INTERVIEW_TIMING": 409,
    "ERR_EMPTY_PANEL": 409,
    "ERR_HEADCOUNT_IMMUTABLE": 422,
    "ERR_OFFER_FIELDS_IMMUTABLE": 422,
}


class ApiError(Exception):
    """Carries error_id, human message, and the HTTP status to return."""

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
        body = error_envelope("ERR_INTERNAL", f"{type(exc).__name__}: {exc}")
        return jsonify(body), 500
