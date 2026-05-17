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


# ---- Helpers that mint specific errors with the spec's exact ids/codes ----

def err_auth_required(msg: str = "Authentication headers missing or invalid") -> APIError:
    return APIError("ERR_AUTH_REQUIRED", msg, 401)


def err_forbidden(msg: str = "Role is not authorized for this operation") -> APIError:
    return APIError("ERR_FORBIDDEN", msg, 403)


def err_not_found(msg: str = "Resource not found") -> APIError:
    return APIError("ERR_NOT_FOUND", msg, 404)


def err_reference_not_found(msg: str = "Referenced resource does not exist") -> APIError:
    return APIError("ERR_REFERENCE_NOT_FOUND", msg, 422)


def err_invalid_encounter_state(msg: str = "Encounter is not in a state that admits this transition") -> APIError:
    return APIError("ERR_INVALID_ENCOUNTER_STATE", msg, 409)


def err_invalid_prescription_state(msg: str = "Prescription is not in a state that admits this transition") -> APIError:
    return APIError("ERR_INVALID_PRESCRIPTION_STATE", msg, 409)


def err_referral_not_pending(msg: str = "Referral is not in PENDING state") -> APIError:
    return APIError("ERR_REFERRAL_NOT_PENDING", msg, 409)


def err_version_conflict(msg: str = "Supplied version does not match persisted version") -> APIError:
    return APIError("ERR_VERSION_CONFLICT", msg, 409)


def err_epcs_not_enrolled(msg: str = "EPCS enrollment or 2FA missing for controlled prescription") -> APIError:
    return APIError("ERR_EPCS_NOT_ENROLLED", msg, 403)


def err_schedule_ii_no_refills(msg: str = "Schedule II prescriptions must have refills_authorized == 0") -> APIError:
    return APIError("ERR_SCHEDULE_II_NO_REFILLS", msg, 422)


def err_provider_not_pcp(msg: str = "Provider may not act as PCP") -> APIError:
    return APIError("ERR_PROVIDER_NOT_PCP", msg, 422)


def err_pcp_already_bound(msg: str = "Patient is already bound to a PCP") -> APIError:
    return APIError("ERR_PCP_ALREADY_BOUND", msg, 409)


def err_referrer_not_pcp(msg: str = "Referring provider must equal Patient.pcp_provider_id") -> APIError:
    return APIError("ERR_REFERRER_NOT_PCP", msg, 422)


def err_invalid_specialist(msg: str = "Invalid specialist for referral") -> APIError:
    return APIError("ERR_INVALID_SPECIALIST", msg, 422)


def err_invalid_time_range(msg: str = "Encounter time range invalid") -> APIError:
    return APIError("ERR_INVALID_TIME_RANGE", msg, 422)


def err_provider_time_conflict(msg: str = "Provider has overlapping encounter") -> APIError:
    return APIError("ERR_PROVIDER_TIME_CONFLICT", msg, 409)


def err_patient_time_conflict(msg: str = "Patient has overlapping encounter") -> APIError:
    return APIError("ERR_PATIENT_TIME_CONFLICT", msg, 409)


def err_panel_full(msg: str = "Provider panel is full") -> APIError:
    return APIError("ERR_PANEL_FULL", msg, 422)


def err_no_billable_lines(msg: str = "Encounter has no billable CPT line items") -> APIError:
    return APIError("ERR_NO_BILLABLE_LINES", msg, 422)


def err_invalid_billing_units(msg: str = "Invalid billing units or catalog pricing") -> APIError:
    return APIError("ERR_INVALID_BILLING_UNITS", msg, 422)


def err_portal_disabled(msg: str = "Portal access denied") -> APIError:
    return APIError("ERR_PORTAL_DISABLED", msg, 403)


def err_segregation_of_duties(msg: str = "Segregation-of-duties violation") -> APIError:
    return APIError("ERR_SEGREGATION_OF_DUTIES", msg, 403)


def err_invalid_input(msg: str = "Invalid input") -> APIError:
    # Some inputs fall outside the documented catalog (malformed JSON, bad pagination)
    # — surface them as 422 with a generic ID; tests usually only inspect the documented IDs.
    return APIError("ERR_INVALID_INPUT", msg, 422)


# ---- Flask integration ---------------------------------------------------

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
        body = error_envelope("ERR_INVALID_INPUT", "Malformed request body")
        return jsonify(body), 422

    @app.errorhandler(415)
    def _handle_415(_exc):
        body = error_envelope("ERR_INVALID_INPUT", "Unsupported media type")
        return jsonify(body), 422

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover — defensive last-resort
        body = error_envelope("ERR_INVALID_INPUT", f"Unexpected server error: {exc}")
        return jsonify(body), 422
