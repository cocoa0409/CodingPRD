"""Custom error definitions and Flask error handlers."""
from __future__ import annotations

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from .response import make_error_envelope


class APIError(Exception):
    """Base API error carrying an error_id, message, and HTTP status."""

    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- Convenience constructors for each catalog entry ---

def err_auth_missing(msg: str = "X-User-ID or X-User-Role header missing or malformed.") -> APIError:
    return APIError("ERR_AUTH_MISSING", msg, 401)


def err_forbidden(msg: str = "Role is not permitted for this endpoint.") -> APIError:
    return APIError("ERR_FORBIDDEN", msg, 403)


def err_segregation_of_duties(msg: str = "Section 2 signer must differ from Section 1 attester.") -> APIError:
    return APIError("ERR_SEGREGATION_OF_DUTIES", msg, 403)


def err_not_found(msg: str = "Resource not found.") -> APIError:
    return APIError("ERR_NOT_FOUND", msg, 404)


def err_reference_not_found(msg: str = "Body foreign-key reference does not resolve.") -> APIError:
    return APIError("ERR_REFERENCE_NOT_FOUND", msg, 404)


def err_invalid_state(msg: str = "Target resource is not in a permitted state for this transition.") -> APIError:
    return APIError("ERR_INVALID_STATE", msg, 409)


def err_form_already_signed(msg: str = "Form has already been signed.") -> APIError:
    return APIError("ERR_FORM_ALREADY_SIGNED", msg, 409)


def err_duplicate_initial_form(msg: str = "An INITIAL form already exists for this employee.") -> APIError:
    return APIError("ERR_DUPLICATE_INITIAL_FORM", msg, 409)


def err_invalid_form_lineage(msg: str = "Invalid form lineage (predecessor missing or out of window).") -> APIError:
    return APIError("ERR_INVALID_FORM_LINEAGE", msg, 422)


def err_document_list_rule(msg: str = "Section 2 must reference exactly List A OR (List B AND List C).") -> APIError:
    return APIError("ERR_DOCUMENT_LIST_RULE", msg, 422)


def err_document_category_mismatch(msg: str = "Document category does not match the referencing field, or document does not belong to employee.") -> APIError:
    return APIError("ERR_DOCUMENT_CATEGORY_MISMATCH", msg, 422)


def err_document_expired(msg: str = "A referenced document is expired.") -> APIError:
    return APIError("ERR_DOCUMENT_EXPIRED", msg, 422)


def err_section2_deadline_missed(msg: str = "Section 2 deadline missed.") -> APIError:
    return APIError("ERR_SECTION2_DEADLINE_MISSED", msg, 409)


def err_case_already_open(msg: str = "Another non-closed E-Verify case already exists for this employee.") -> APIError:
    return APIError("ERR_CASE_ALREADY_OPEN", msg, 409)


def err_tnc_deadline_passed(msg: str = "TNC contest deadline has passed.") -> APIError:
    return APIError("ERR_TNC_DEADLINE_PASSED", msg, 409)


def err_everify_submission_late(msg: str = "E-Verify submission is past the 3-day window.") -> APIError:
    return APIError("ERR_EVERIFY_SUBMISSION_LATE", msg, 409)


def err_stem_extension_late(msg: str = "STEM extension cannot be applied to a lapsed EAD.") -> APIError:
    return APIError("ERR_STEM_EXTENSION_LATE", msg, 422)


def err_version_conflict(msg: str = "Version conflict (OCC).") -> APIError:
    return APIError("ERR_VERSION_CONFLICT", msg, 409)


def err_pagination(msg: str = "Pagination parameters out of range.") -> APIError:
    return APIError("ERR_PAGINATION", msg, 400)


def err_validation(msg: str = "Request validation failed.") -> APIError:
    return APIError("ERR_VALIDATION", msg, 422)


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
        # Body parsing failures and other werkzeug errors → generic validation
        if exc.code and 400 <= exc.code < 500:
            body = make_error_envelope("ERR_VALIDATION", exc.description or "Bad request.")
            return jsonify(body), 422
        body = make_error_envelope("ERR_VALIDATION", "Server error.")
        return jsonify(body), 422

    @app.errorhandler(Exception)
    def _handle_uncaught(exc: Exception):
        # Defensive — never let a 500 leak in undefined shape
        body = make_error_envelope("ERR_VALIDATION", f"Unhandled error: {exc!r}")
        return jsonify(body), 422
