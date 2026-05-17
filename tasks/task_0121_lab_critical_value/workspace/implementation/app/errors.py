"""Error definitions and Flask error handlers — IDs and HTTP codes per scaffold §1.6."""
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


# ---------------------------------------------------------------------------
# Specific error factories — every id maps to scaffold's §1.6 error catalog.
# ---------------------------------------------------------------------------

def err_auth_required(msg: str = "X-User-ID and X-User-Role headers are required") -> APIError:
    return APIError("ERR_AUTH_REQUIRED", msg, 401)


def err_forbidden(msg: str = "Role is not authorized for this endpoint") -> APIError:
    return APIError("ERR_FORBIDDEN", msg, 403)


def err_not_found(msg: str = "Resource not found") -> APIError:
    return APIError("ERR_NOT_FOUND", msg, 404)


def err_invalid_state(msg: str = "Resource is not in a valid state for this transition") -> APIError:
    return APIError("ERR_INVALID_STATE", msg, 409)


def err_version_conflict(msg: str = "Supplied version does not match server version") -> APIError:
    return APIError("ERR_VERSION_CONFLICT", msg, 409)


def err_clia_sod_violation(msg: str = "released_by_id must differ from resulted_by_id (CLIA SoD)") -> APIError:
    return APIError("ERR_CLIA_SOD_VIOLATION", msg, 422)


def err_clia_complexity_violation(msg: str = "Clinician role not permitted for this panel's CLIA complexity") -> APIError:
    return APIError("ERR_CLIA_COMPLEXITY_VIOLATION", msg, 422)


def err_patient_consent_blocked(msg: str = "Patient notification consent blocks this release") -> APIError:
    return APIError("ERR_PATIENT_CONSENT_BLOCKED", msg, 422)


def err_ack_by_wrong_recipient(msg: str = "acknowledged_by_id must equal recipient_clinician_id") -> APIError:
    return APIError("ERR_ACK_BY_WRONG_RECIPIENT", msg, 422)


def err_readback_incomplete(msg: str = "read_back_text must contain every critical analyte code") -> APIError:
    return APIError("ERR_READBACK_INCOMPLETE", msg, 422)


def err_time_order_invalid(msg: str = "Timestamp ordering invalid") -> APIError:
    return APIError("ERR_TIME_ORDER_INVALID", msg, 422)


def err_transport_chain_broken(msg: str = "Transport leg chain monotonicity violated") -> APIError:
    return APIError("ERR_TRANSPORT_CHAIN_BROKEN", msg, 422)


def err_measurements_incomplete(msg: str = "measurements do not cover panel analytes correctly") -> APIError:
    return APIError("ERR_MEASUREMENTS_INCOMPLETE", msg, 422)


def err_clinician_inactive(msg: str = "Referenced clinician is not active") -> APIError:
    return APIError("ERR_CLINICIAN_INACTIVE", msg, 422)


def err_already_acknowledged(msg: str = "Notification has already been acknowledged") -> APIError:
    return APIError("ERR_ALREADY_ACKNOWLEDGED", msg, 409)


def err_leg_already_arrived(msg: str = "Transport leg has already been marked ARRIVED") -> APIError:
    return APIError("ERR_LEG_ALREADY_ARRIVED", msg, 409)


def err_specimen_already_exists(msg: str = "A specimen already exists for this LabOrder") -> APIError:
    return APIError("ERR_SPECIMEN_ALREADY_EXISTS", msg, 409)


def err_invalid_pagination(msg: str = "Pagination parameters out of range") -> APIError:
    return APIError("ERR_INVALID_PAGINATION", msg, 400)


def err_validation(msg: str = "Input validation failed") -> APIError:
    return APIError("ERR_VALIDATION", msg, 422)


# ---------------------------------------------------------------------------
# Flask integration
# ---------------------------------------------------------------------------

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
        return jsonify(body), 422

    @app.errorhandler(415)
    def _handle_415(_exc):
        body = error_envelope("ERR_VALIDATION", "Unsupported media type")
        return jsonify(body), 422

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover — defensive
        body = error_envelope("ERR_VALIDATION", f"Unexpected server error: {exc}")
        return jsonify(body), 422
