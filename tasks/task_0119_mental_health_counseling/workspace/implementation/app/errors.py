"""Error definitions and Flask error handlers. Error IDs/codes copied verbatim from §1.6 of SCAFFOLD."""
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


# ---- Specific error factories (IDs/HTTP codes per scaffold §1.6) -------------

def err_auth_required(msg: str = "Authentication headers missing or invalid") -> APIError:
    return APIError("ERR_AUTH_REQUIRED", msg, 401)


def err_forbidden(msg: str = "Role is not authorized for this operation") -> APIError:
    return APIError("ERR_FORBIDDEN", msg, 403)


def err_not_found(msg: str = "Resource not found") -> APIError:
    return APIError("ERR_NOT_FOUND", msg, 404)


def err_reference_not_found(msg: str = "Referenced resource does not exist") -> APIError:
    return APIError("ERR_REFERENCE_NOT_FOUND", msg, 404)


def err_validation(msg: str = "Schema validation failed") -> APIError:
    return APIError("ERR_VALIDATION", msg, 400)


def err_invalid_amount(msg: str = "Monetary amount must be a non-negative integer") -> APIError:
    return APIError("ERR_INVALID_AMOUNT", msg, 422)


def err_invalid_timerange(msg: str = "Invalid time range") -> APIError:
    return APIError("ERR_INVALID_TIMERANGE", msg, 422)


def err_invalid_state(msg: str = "Entity is not in a state that admits this transition") -> APIError:
    return APIError("ERR_INVALID_STATE", msg, 409)


def err_session_not_open(msg: str = "Session is not open for this transition") -> APIError:
    return APIError("ERR_SESSION_NOT_OPEN", msg, 409)


def err_appt_not_open(msg: str = "Appointment is not open for this transition") -> APIError:
    return APIError("ERR_APPT_NOT_OPEN", msg, 409)


def err_claim_not_posted(msg: str = "Claim is not in POSTED state") -> APIError:
    return APIError("ERR_CLAIM_NOT_POSTED", msg, 409)


def err_void_window_expired(msg: str = "Claim void window (7 days) has expired") -> APIError:
    return APIError("ERR_VOID_WINDOW_EXPIRED", msg, 409)


def err_safety_plan_required(msg: str = "An active safety plan is required for this patient") -> APIError:
    return APIError("ERR_SAFETY_PLAN_REQUIRED", msg, 409)


def err_high_assessment_required(
    msg: str = "trigger_assessment_id must reference a HIGH crisis assessment for this patient",
) -> APIError:
    return APIError("ERR_HIGH_ASSESSMENT_REQUIRED", msg, 422)


def err_risk_still_high(msg: str = "Cannot rescind: latest crisis assessment is still HIGH") -> APIError:
    return APIError("ERR_RISK_STILL_HIGH", msg, 409)


def err_therapist_not_active(msg: str = "Therapist credential_status is not ACTIVE/PROVISIONAL") -> APIError:
    return APIError("ERR_THERAPIST_NOT_ACTIVE", msg, 409)


def err_license_gap_for_state(msg: str = "Therapist has no active license for this state") -> APIError:
    return APIError("ERR_LICENSE_GAP_FOR_STATE", msg, 409)


def err_no_active_license(msg: str = "Therapist has no ACTIVE state license") -> APIError:
    return APIError("ERR_NO_ACTIVE_LICENSE", msg, 409)


def err_no_active_supervisor(msg: str = "No ACTIVE supervision assignment for this pre-licensed therapist") -> APIError:
    return APIError("ERR_NO_ACTIVE_SUPERVISOR", msg, 409)


def err_supervision_incomplete(
    msg: str = "Pre-licensed therapist needs >= 3000 supervised hours and an ACTIVE supervision assignment",
) -> APIError:
    return APIError("ERR_SUPERVISION_INCOMPLETE", msg, 409)


def err_therapist_double_booked(msg: str = "Therapist has an overlapping appointment") -> APIError:
    return APIError("ERR_THERAPIST_DOUBLE_BOOKED", msg, 409)


def err_patient_double_booked(msg: str = "Patient has an appointment within the 5-minute gap") -> APIError:
    return APIError("ERR_PATIENT_DOUBLE_BOOKED", msg, 409)


def err_outside_checkin_window(msg: str = "Check-in is outside the [-15m, +30m] window") -> APIError:
    return APIError("ERR_OUTSIDE_CHECKIN_WINDOW", msg, 409)


def err_version_conflict(msg: str = "Supplied version does not match persisted version") -> APIError:
    return APIError("ERR_VERSION_CONFLICT", msg, 409)


# ---- Flask integration -------------------------------------------------------

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
    def _handle_unexpected(exc):  # pragma: no cover — defensive last-resort
        if isinstance(exc, APIError):
            body = error_envelope(exc.error_id, exc.message)
            return jsonify(body), exc.http_status
        body = error_envelope("ERR_VALIDATION", f"Unexpected server error: {exc}")
        return jsonify(body), 400
