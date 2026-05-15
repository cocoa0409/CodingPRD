"""Custom exception type and Flask error-handler registration."""
from __future__ import annotations

from typing import Any

from flask import Flask, jsonify

from .response import error_envelope


# Mapping of error_id -> http status (per scaffold §1.6 / PRD §5)
ERROR_HTTP_STATUS: dict[str, int] = {
    "ERR_AUTH_REQUIRED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_INVALID_SESSION_STATE": 409,
    "ERR_COURSE_NOT_ON_SHELF": 409,
    "ERR_INSTRUCTOR_BLACKLISTED": 422,
    "ERR_INSTRUCTOR_EXPERTISE_MISMATCH": 422,
    "ERR_INSTRUCTOR_UNAVAILABLE": 409,
    "ERR_CLASSROOM_CONFLICT": 409,
    "ERR_ONLINE_ROOM_CAPACITY_EXCEEDED": 409,
    "ERR_PREREQUISITE_NOT_MET": 422,
    "ERR_PREREQUISITE_CYCLE": 422,
    "ERR_CATEGORY_CYCLE": 422,
    "ERR_ENROLLMENT_DEADLINE_PASSED": 409,
    "ERR_SESSION_AT_CAPACITY": 409,
    "ERR_DUPLICATE_ENROLLMENT": 409,
    "ERR_WAITLIST_PROMOTION_RACE": 409,
    "ERR_COURSE_VERSION_RACE": 409,
    "ERR_CERT_TEMPLATE_MISSING": 422,
    "ERR_CHECKIN_INVALID": 422,
    "ERR_INCOMPLETE_EXAM": 422,
    "ERR_RENEWAL_WINDOW_INVALID": 422,
    "ERR_CREDIT_NEGATIVE": 422,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_VERSION_CONFLICT": 409,
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
        body = error_envelope("ERR_RESOURCE_NOT_FOUND", "Resource not found.")
        return jsonify(body), 404

    @app.errorhandler(405)
    def _handle_405(_exc):
        body = error_envelope("ERR_RESOURCE_NOT_FOUND", "Method not allowed.")
        return jsonify(body), 404

    @app.errorhandler(400)
    def _handle_400(_exc):
        body = error_envelope("ERR_INVALID_PAGINATION", "Bad request.")
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def _handle_generic(exc):  # noqa: ANN001
        body = error_envelope("ERR_RESOURCE_NOT_FOUND", f"Unhandled error: {exc.__class__.__name__}: {exc}")
        return jsonify(body), 500
