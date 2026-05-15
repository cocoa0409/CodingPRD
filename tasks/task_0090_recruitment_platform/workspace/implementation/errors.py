"""Error definitions and Flask error handlers."""
from __future__ import annotations

from flask import Flask, jsonify

from response import error_response


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = "") -> None:
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Catalog (id, http, default message)
ERR_AUTH_MISSING = ("ERR_AUTH_MISSING", 401, "Authentication headers missing.")
ERR_AUTH_INVALID_ROLE = ("ERR_AUTH_INVALID_ROLE", 401, "Unknown role.")
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403, "Role not permitted.")
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404, "Resource not found.")
ERR_REFERENCE_NOT_FOUND = ("ERR_REFERENCE_NOT_FOUND", 404, "Referenced resource not found.")
ERR_HR_NOT_BOUND = ("ERR_HR_NOT_BOUND", 403, "HR user is not bound to the target company.")
ERR_RESUME_NOT_VISIBLE = ("ERR_RESUME_NOT_VISIBLE", 403, "Candidate resume is not visible.")
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409, "Invalid state transition.")
ERR_PROHIBITED_CONTENT = ("ERR_PROHIBITED_CONTENT", 422, "Prohibited content detected.")
ERR_DUPLICATE_POSTING = ("ERR_DUPLICATE_POSTING", 409, "Duplicate posting.")
ERR_SEGREGATION_VIOLATION = ("ERR_SEGREGATION_VIOLATION", 422, "Segregation of duties violated.")
ERR_OFFER_EXPIRED = ("ERR_OFFER_EXPIRED", 409, "Offer acceptance window expired.")
ERR_SLOT_IN_PAST = ("ERR_SLOT_IN_PAST", 422, "Proposed slot in the past.")
ERR_INTERVIEWER_BUSY = ("ERR_INTERVIEWER_BUSY", 409, "Interviewer is busy.")
ERR_CANDIDATE_RATE_LIMIT = ("ERR_CANDIDATE_RATE_LIMIT", 429, "Too many applications.")
ERR_POSTING_QUOTA_EXCEEDED = ("ERR_POSTING_QUOTA_EXCEEDED", 409, "Posting quota exceeded.")
ERR_INVALID_AMOUNT = ("ERR_INVALID_AMOUNT", 422, "Invalid amount.")
ERR_INVALID_SALARY_RANGE = ("ERR_INVALID_SALARY_RANGE", 422, "Invalid salary range.")
ERR_ONBOARDING_ALREADY_EXISTS = ("ERR_ONBOARDING_ALREADY_EXISTS", 409, "Onboarding already exists for this offer.")
ERR_VERSION_CONFLICT = ("ERR_VERSION_CONFLICT", 409, "Version conflict.")
ERR_VALIDATION = ("ERR_VALIDATION", 422, "Validation error.")
ERR_FEEDBACK_INVALID = ("ERR_FEEDBACK_INVALID", 422, "Feedback decision invalid.")
ERR_CHECK_INVALID = ("ERR_CHECK_INVALID", 422, "Check parameter invalid.")


def raise_err(catalog_entry, message: str = "") -> None:
    eid, http, default_msg = catalog_entry
    raise ApiError(eid, http, message or default_msg)


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError):
        body, status = error_response(exc.error_id, exc.message, exc.http_status)
        return jsonify(body), status

    @app.errorhandler(404)
    def _handle_404(_exc):
        body, status = error_response(
            "ERR_NOT_FOUND", "Route not found.", 404
        )
        return jsonify(body), status

    @app.errorhandler(405)
    def _handle_405(_exc):
        body, status = error_response(
            "ERR_NOT_FOUND", "Method not allowed.", 404
        )
        return jsonify(body), status

    @app.errorhandler(400)
    def _handle_400(_exc):
        body, status = error_response(
            "ERR_VALIDATION", "Malformed request.", 422
        )
        return jsonify(body), status

    @app.errorhandler(Exception)
    def _handle_uncaught(exc):
        # Surface unexpected errors as ERR_VALIDATION so the client gets the envelope.
        body, status = error_response(
            "ERR_VALIDATION", f"Server error: {exc}", 422
        )
        return jsonify(body), status
