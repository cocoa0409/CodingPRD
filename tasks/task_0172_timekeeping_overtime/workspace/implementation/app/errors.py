"""Custom error definitions and Flask error handlers.

The catalog mirrors §1.6 of the scaffold and §5 of the PRD.
"""
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


# --- Auth ---------------------------------------------------------------

def err_auth_required(msg: str = "X-User-ID or X-User-Role header missing.") -> APIError:
    return APIError("ERR_AUTH_REQUIRED", msg, 401)


def err_invalid_role(msg: str = "X-User-Role is not one of {Employee, Supervisor, PayrollAdmin}.") -> APIError:
    return APIError("ERR_INVALID_ROLE", msg, 401)


def err_forbidden(msg: str = "Role lacks permission for this operation.") -> APIError:
    return APIError("ERR_FORBIDDEN", msg, 403)


# --- Existence ---------------------------------------------------------

def err_not_found(msg: str = "Referenced resource does not exist.") -> APIError:
    return APIError("ERR_RESOURCE_NOT_FOUND", msg, 404)


# --- State -------------------------------------------------------------

def err_shift_invalid_state(msg: str = "Shift is not in a permitted state for this action.") -> APIError:
    return APIError("ERR_SHIFT_INVALID_STATE", msg, 409)


def err_shift_already_open(msg: str = "Shift has already transitioned out of SCHEDULED.") -> APIError:
    return APIError("ERR_SHIFT_ALREADY_OPEN", msg, 409)


def err_time_edit_not_pending(msg: str = "TimeEdit is not in the required state for this action.") -> APIError:
    return APIError("ERR_TIME_EDIT_NOT_PENDING", msg, 409)


def err_workweek_locked(msg: str = "Workweek is LOCKED; mutation forbidden.") -> APIError:
    return APIError("ERR_WORKWEEK_LOCKED", msg, 409)


# --- Business safety ---------------------------------------------------

def err_segregation_of_duties(msg: str = "Approver must differ from requester (segregation of duties).") -> APIError:
    return APIError("ERR_SEGREGATION_OF_DUTIES", msg, 403)


def err_fraud_requires_admin(msg: str = "FRAUD_CORRECTION TimeEdits require a PayrollAdmin approver.") -> APIError:
    return APIError("ERR_FRAUD_REQUIRES_ADMIN", msg, 403)


def err_exempt_not_eligible(msg: str = "Exempt employees may not produce Shift punches.") -> APIError:
    return APIError("ERR_EXEMPT_NOT_ELIGIBLE", msg, 422)


def err_punch_out_of_order(msg: str = "Punch sequence violates IN → (MEAL_OUT → MEAL_IN)? → OUT.") -> APIError:
    return APIError("ERR_PUNCH_OUT_OF_ORDER", msg, 422)


def err_meal_break_duplicate(msg: str = "A MealBreak already exists for this shift.") -> APIError:
    return APIError("ERR_MEAL_BREAK_DUPLICATE", msg, 409)


def err_punch_outside_window(msg: str = "IN punch outside [scheduled_start - 60m, scheduled_end + 60m].") -> APIError:
    return APIError("ERR_PUNCH_OUTSIDE_WINDOW", msg, 422)


def err_time_edit_out_of_range(msg: str = "proposed_punched_at outside [scheduled_start - 4h, scheduled_end + 6h].") -> APIError:
    return APIError("ERR_TIME_EDIT_OUT_OF_RANGE", msg, 422)


def err_workweek_bad_anchor(msg: str = "week_start must be Sunday 00:00:00.000 UTC.") -> APIError:
    return APIError("ERR_WORKWEEK_BAD_ANCHOR", msg, 422)


def err_tipped_fields_mismatch(msg: str = "Tipped fields are not internally consistent with tipped_role.") -> APIError:
    return APIError("ERR_TIPPED_FIELDS_MISMATCH", msg, 422)


def err_tips_not_applicable(msg: str = "TipDeclaration submitted on a non-tipped employee or with invalid tips.") -> APIError:
    return APIError("ERR_TIPS_NOT_APPLICABLE", msg, 422)


def err_below_minimum_wage(msg: str = "Configured wage cannot satisfy minimum-wage floor.") -> APIError:
    return APIError("ERR_BELOW_MINIMUM_WAGE", msg, 422)


def err_version_conflict(msg: str = "OCC version supplied does not match current.") -> APIError:
    return APIError("ERR_VERSION_CONFLICT", msg, 409)


def err_duplicate_idempotency_key(msg: str = "Idempotency key reused with conflicting payload.") -> APIError:
    return APIError("ERR_DUPLICATE_IDEMPOTENCY_KEY", msg, 409)


def err_invalid_input(msg: str = "Request validation failed.") -> APIError:
    return APIError("ERR_INVALID_INPUT", msg, 422)


# --- Flask error handlers ---------------------------------------------

def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(APIError)
    def _handle_api_error(exc: APIError):
        body = make_error_envelope(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def _handle_404(_exc):
        body = make_error_envelope("ERR_RESOURCE_NOT_FOUND", "Resource not found.")
        return jsonify(body), 404

    @app.errorhandler(405)
    def _handle_405(_exc):
        body = make_error_envelope("ERR_RESOURCE_NOT_FOUND", "Method or path not supported.")
        return jsonify(body), 404

    @app.errorhandler(HTTPException)
    def _handle_http(exc: HTTPException):
        # Body-parsing failures and werkzeug 4xx → generic input failure
        if exc.code and 400 <= exc.code < 500:
            body = make_error_envelope("ERR_INVALID_INPUT", exc.description or "Bad request.")
            return jsonify(body), 422
        body = make_error_envelope("ERR_INVALID_INPUT", "Server error.")
        return jsonify(body), 422

    @app.errorhandler(Exception)
    def _handle_uncaught(exc: Exception):
        # Defensive: never leak undefined-shape 500s.
        body = make_error_envelope("ERR_INVALID_INPUT", f"Unhandled error: {exc!r}")
        return jsonify(body), 422
