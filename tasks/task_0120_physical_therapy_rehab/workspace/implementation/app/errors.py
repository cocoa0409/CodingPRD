"""Error definitions and Flask error handlers."""
from __future__ import annotations

from flask import Flask, jsonify

from .responses import error_envelope


class APIError(Exception):
    """Raised by routes/services to surface a structured error response."""

    def __init__(self, error_id: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Auth/authz
def err_auth_missing(msg: str = "Authentication headers missing or empty") -> APIError:
    return APIError("ERR_AUTH_MISSING", msg, 401)


def err_forbidden(msg: str = "Role not authorized for this endpoint") -> APIError:
    return APIError("ERR_FORBIDDEN", msg, 403)


# Existence
def err_not_found(msg: str = "Resource not found") -> APIError:
    return APIError("ERR_NOT_FOUND", msg, 404)


def err_reference_not_found(msg: str = "Referenced resource does not exist") -> APIError:
    return APIError("ERR_REFERENCE_NOT_FOUND", msg, 404)


# State
def err_invalid_state(msg: str = "Operation invoked on a resource not in the required status") -> APIError:
    return APIError("ERR_INVALID_STATE", msg, 409)


def err_episode_not_active(msg: str = "Episode is not in ACTIVE state") -> APIError:
    return APIError("ERR_EPISODE_NOT_ACTIVE", msg, 409)


def err_reeval_due(msg: str = "Episode is in REEVAL_DUE; reevaluation required") -> APIError:
    return APIError("ERR_REEVAL_DUE", msg, 409)


# Business
def err_therapist_not_licensed(msg: str = "Therapist not licensed to evaluate") -> APIError:
    return APIError("ERR_THERAPIST_NOT_LICENSED_TO_EVALUATE", msg, 403)


def err_segregation_of_duties(msg: str = "Discharge signer must differ from latest evaluator") -> APIError:
    return APIError("ERR_SEGREGATION_OF_DUTIES", msg, 422)


def err_veteran_referral_required(msg: str = "VA referral authorization required on episode") -> APIError:
    return APIError("ERR_VETERAN_REFERRAL_REQUIRED", msg, 422)


def err_va_reference_mismatch(msg: str = "Authorization.external_reference does not match VA referral and patient") -> APIError:
    return APIError("ERR_VA_REFERENCE_MISMATCH", msg, 422)


def err_va_referral_exhausted(msg: str = "VA referral has insufficient units for this authorization") -> APIError:
    return APIError("ERR_VA_REFERRAL_EXHAUSTED", msg, 409)


def err_cert_period_too_long(msg: str = "PlanOfCare cert window > 90 days or end <= start") -> APIError:
    return APIError("ERR_CERT_PERIOD_TOO_LONG", msg, 422)


def err_out_of_auth_window(msg: str = "Visit scheduled_start outside authorization or plan window") -> APIError:
    return APIError("ERR_OUT_OF_AUTH_WINDOW", msg, 422)


def err_clinician_double_booked(msg: str = "Clinician has overlapping visit (half-open)") -> APIError:
    return APIError("ERR_CLINICIAN_DOUBLE_BOOKED", msg, 409)


def err_patient_double_booked(msg: str = "Patient has overlapping visit (closed)") -> APIError:
    return APIError("ERR_PATIENT_DOUBLE_BOOKED", msg, 409)


def err_poc_visit_limit(msg: str = "Visits on plan exceed PlanOfCare.planned_visit_count") -> APIError:
    return APIError("ERR_POC_VISIT_LIMIT", msg, 422)


def err_insufficient_units(msg: str = "Insufficient authorized units for this visit") -> APIError:
    return APIError("ERR_INSUFFICIENT_UNITS", msg, 422)


def err_cap_exceeded(msg: str = "Sign would push ytd_capped_amount_cents past hard cap") -> APIError:
    return APIError("ERR_CAP_EXCEEDED", msg, 422)


def err_invalid_mips_exception(msg: str = "MipsMeasure exception/numerator combination invalid") -> APIError:
    return APIError("ERR_INVALID_MIPS_EXCEPTION", msg, 422)


def err_pagination_range(msg: str = "limit must be in [1,100] and offset >= 0") -> APIError:
    return APIError("ERR_PAGINATION_RANGE", msg, 400)


def err_version_conflict(msg: str = "Supplied version does not match persisted version") -> APIError:
    return APIError("ERR_VERSION_CONFLICT", msg, 409)


def err_duplicate_npi(msg: str = "Therapist with this NPI already exists") -> APIError:
    return APIError("ERR_DUPLICATE_NPI", msg, 409)


def err_validation(msg: str = "Validation failure") -> APIError:
    return APIError("ERR_VALIDATION", msg, 400)


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(APIError)
    def _handle_api_error(exc: APIError):
        body = error_envelope(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def _handle_404(_exc):
        body = error_envelope("ERR_NOT_FOUND", "Resource not found")
        return jsonify(body), 404

    @app.errorhandler(405)
    def _handle_405(_exc):
        body = error_envelope("ERR_NOT_FOUND", "Method not allowed for this path")
        return jsonify(body), 404

    @app.errorhandler(400)
    def _handle_400(_exc):
        body = error_envelope("ERR_VALIDATION", "Malformed request body")
        return jsonify(body), 400

    @app.errorhandler(415)
    def _handle_415(_exc):
        body = error_envelope("ERR_VALIDATION", "Unsupported media type")
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover
        body = error_envelope("ERR_VALIDATION", f"Unexpected server error: {exc}")
        return jsonify(body), 400
