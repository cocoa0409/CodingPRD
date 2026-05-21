"""Custom error class + Flask error handlers."""
from __future__ import annotations

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from .response import make_error_envelope


class APIError(Exception):
    """Carries an `error_id`, `message`, and `http_status`."""

    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- Convenience constructors (one per catalog entry) ---


def err_missing_auth(msg: str = "X-User-ID or X-User-Role header missing or empty.") -> APIError:
    return APIError("ERR_MISSING_AUTH_HEADERS", msg, 401)


def err_unknown_role(msg: str = "X-User-Role is not one of the declared roles.") -> APIError:
    return APIError("ERR_UNKNOWN_ROLE", msg, 401)


def err_unknown_identity(msg: str = "X-User-ID does not resolve to a known entity.") -> APIError:
    return APIError("ERR_UNKNOWN_IDENTITY", msg, 401)


def err_forbidden(msg: str = "Role is not permitted for this endpoint.") -> APIError:
    return APIError("ERR_FORBIDDEN", msg, 403)


def err_not_owner(msg: str = "Employee does not own the target resource.") -> APIError:
    return APIError("ERR_NOT_OWNER", msg, 403)


def err_not_found(msg: str = "Resource not found.") -> APIError:
    return APIError("ERR_NOT_FOUND", msg, 404)


def err_invalid_state(msg: str = "Target resource is not in a permitted state for this transition.") -> APIError:
    return APIError("ERR_INVALID_STATE", msg, 409)


def err_version_conflict(msg: str = "Version conflict (OCC).") -> APIError:
    return APIError("ERR_VERSION_CONFLICT", msg, 409)


def err_employee_terminated(msg: str = "Employee is TERMINATED; mutations refused.") -> APIError:
    return APIError("ERR_EMPLOYEE_TERMINATED", msg, 409)


def err_not_eligible_tenure(msg: str = "Months of service below 12.") -> APIError:
    return APIError("ERR_NOT_ELIGIBLE_TENURE", msg, 422)


def err_not_eligible_hours(msg: str = "Hours worked in trailing 12 months below 1250.") -> APIError:
    return APIError("ERR_NOT_ELIGIBLE_HOURS", msg, 422)


def err_not_eligible_worksite(msg: str = "Worksite headcount within 75 miles below 50.") -> APIError:
    return APIError("ERR_NOT_ELIGIBLE_WORKSITE", msg, 422)


def err_cert_deadline_missed(msg: str = "Certification deadline expired before approval.") -> APIError:
    return APIError("ERR_CERT_DEADLINE_MISSED", msg, 422)


def err_cert_incomplete(msg: str = "Cannot approve while certification is incomplete.") -> APIError:
    return APIError("ERR_CERT_INCOMPLETE", msg, 422)


def err_quota_exceeded(msg: str = "FMLA quota would be exceeded.") -> APIError:
    return APIError("ERR_QUOTA_EXCEEDED", msg, 422)


def err_instance_not_allowed(msg: str = "Instance not allowed for this case or hours_used out of range.") -> APIError:
    return APIError("ERR_INSTANCE_NOT_ALLOWED", msg, 422)


def err_instance_overlap(msg: str = "Cross-case instance overlap for this employee on this date.") -> APIError:
    return APIError("ERR_INSTANCE_OVERLAP", msg, 422)


def err_pfl_not_available(msg: str = "State PFL program not available or weeks_authorized out of range.") -> APIError:
    return APIError("ERR_PFL_NOT_AVAILABLE", msg, 422)


def err_pfl_mismatch(msg: str = "PfLClaim linkage inconsistent (wrong employee or claim_type mismatch).") -> APIError:
    return APIError("ERR_PFL_MISMATCH", msg, 422)


def err_job_restoration_forfeited(msg: str = "Job restoration is forfeited or not protected.") -> APIError:
    return APIError("ERR_JOB_RESTORATION_FORFEITED", msg, 409)


def err_invoice_not_payable(msg: str = "Invoice is not in a payable state.") -> APIError:
    return APIError("ERR_INVOICE_NOT_PAYABLE", msg, 409)


def err_duplicate_instance_day(msg: str = "A LeaveInstance for this case and date already exists.") -> APIError:
    return APIError("ERR_DUPLICATE_INSTANCE_DAY", msg, 409)


def err_validation(msg: str = "Request body validation failed.") -> APIError:
    return APIError("ERR_VALIDATION", msg, 400)


# --- Flask error handlers ---


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(APIError)
    def _handle_api_error(exc: APIError):
        body = make_error_envelope(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def _handle_not_found(_exc):
        body = make_error_envelope("ERR_NOT_FOUND", "Resource not found.")
        return jsonify(body), 404

    @app.errorhandler(405)
    def _handle_method_not_allowed(_exc):
        body = make_error_envelope("ERR_NOT_FOUND", "Method or path not supported.")
        return jsonify(body), 404

    @app.errorhandler(HTTPException)
    def _handle_http(exc: HTTPException):
        if exc.code and 400 <= exc.code < 500:
            body = make_error_envelope("ERR_VALIDATION", exc.description or "Bad request.")
            return jsonify(body), 400
        body = make_error_envelope("ERR_VALIDATION", "Server error.")
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def _handle_uncaught(exc: Exception):
        body = make_error_envelope("ERR_VALIDATION", f"Unhandled error: {exc!r}")
        return jsonify(body), 400
