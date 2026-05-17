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


def err_sod_violation(msg: str = "Segregation of duties violated") -> APIError:
    return APIError("ERR_SOD_VIOLATION", msg, 403)


def err_not_found(msg: str = "Resource not found") -> APIError:
    return APIError("ERR_NOT_FOUND", msg, 404)


def err_invalid_state(msg: str = "Invalid state for requested transition") -> APIError:
    return APIError("ERR_INVALID_STATE", msg, 409)


def err_irb_expired(msg: str = "IRB approval has expired") -> APIError:
    return APIError("ERR_IRB_EXPIRED", msg, 409)


def err_randomization_misconfigured(msg: str = "Randomization configuration invalid") -> APIError:
    return APIError("ERR_RANDOMIZATION_MISCONFIGURED", msg, 422)


def err_consent_version_stale(msg: str = "Consent version is stale") -> APIError:
    return APIError("ERR_CONSENT_VERSION_STALE", msg, 409)


def err_trial_full(msg: str = "Trial enrollment cap reached") -> APIError:
    return APIError("ERR_TRIAL_FULL", msg, 409)


def err_stratum_key_missing(msg: str = "Stratification field missing from participant profile") -> APIError:
    return APIError("ERR_STRATUM_KEY_MISSING", msg, 422)


def err_ae_blocking(msg: str = "An open adverse event blocks this operation") -> APIError:
    return APIError("ERR_AE_BLOCKING", msg, 409)


def err_draw_outside_window(msg: str = "Blood draw outside the protocol window") -> APIError:
    return APIError("ERR_DRAW_OUTSIDE_WINDOW", msg, 409)


def err_window_not_yet_passed(msg: str = "Visit window has not yet fully elapsed") -> APIError:
    return APIError("ERR_WINDOW_NOT_YET_PASSED", msg, 409)


def err_duplicate_visit_sequence(msg: str = "Visit sequence_no already exists for this participant") -> APIError:
    return APIError("ERR_DUPLICATE_VISIT_SEQUENCE", msg, 409)


def err_duplicate_protocol_code(msg: str = "protocol_code is not unique") -> APIError:
    return APIError("ERR_DUPLICATE_PROTOCOL_CODE", msg, 409)


def err_cross_participant_reference(msg: str = "Referenced visit belongs to a different participant") -> APIError:
    return APIError("ERR_CROSS_PARTICIPANT_REFERENCE", msg, 422)


def err_version_conflict(msg: str = "Stale version supplied for optimistic concurrency check") -> APIError:
    return APIError("ERR_VERSION_CONFLICT", msg, 409)


def err_invalid_input(msg: str = "Invalid input") -> APIError:
    return APIError("ERR_INVALID_INPUT", msg, 422)


def err_no_arms_defined(msg: str = "Trial has no arms defined") -> APIError:
    return APIError("ERR_NO_ARMS_DEFINED", msg, 422)


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
