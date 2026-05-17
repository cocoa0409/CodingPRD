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
# Error factories — every id maps to scaffold's §1.6 error catalog.
# ---------------------------------------------------------------------------

def err_auth_missing(msg: str = "X-User-ID and X-User-Role headers are required and non-empty") -> APIError:
    return APIError("ERR_AUTH_MISSING", msg, 401)


def err_auth_invalid_role(msg: str = "X-User-Role is not one of the recognized roles") -> APIError:
    return APIError("ERR_AUTH_INVALID_ROLE", msg, 401)


def err_forbidden(msg: str = "Role is not authorized for this endpoint") -> APIError:
    return APIError("ERR_FORBIDDEN", msg, 403)


def err_not_found(msg: str = "Resource not found") -> APIError:
    return APIError("ERR_NOT_FOUND", msg, 404)


def err_validation(msg: str = "Input validation failed") -> APIError:
    return APIError("ERR_VALIDATION", msg, 400)


def err_account_frozen(msg: str = "Account is FROZEN; operation not permitted") -> APIError:
    return APIError("ERR_ACCOUNT_FROZEN", msg, 409)


def err_account_closed(msg: str = "Account is CLOSED; operation not permitted") -> APIError:
    return APIError("ERR_ACCOUNT_CLOSED", msg, 409)


def err_invalid_state(msg: str = "Resource is not in a valid state for this transition") -> APIError:
    return APIError("ERR_INVALID_STATE", msg, 409)


def err_participant_deceased(msg: str = "Participant is deceased; operation not permitted") -> APIError:
    return APIError("ERR_PARTICIPANT_DECEASED", msg, 409)


def err_inherited_claim_forfeited(msg: str = "Beneficiary claim has been FORFEITED") -> APIError:
    return APIError("ERR_INHERITED_CLAIM_FORFEITED", msg, 409)


def err_secure_deadline_expired(msg: str = "SECURE Act deadline has expired for this inherited account") -> APIError:
    return APIError("ERR_SECURE_DEADLINE_EXPIRED", msg, 422)


def err_invalid_conversion_pair(msg: str = "Conversion must be from TRADITIONAL to ROTH") -> APIError:
    return APIError("ERR_INVALID_CONVERSION_PAIR", msg, 422)


def err_cross_participant_conversion(msg: str = "Conversion accounts must belong to the same participant") -> APIError:
    return APIError("ERR_CROSS_PARTICIPANT_CONVERSION", msg, 422)


def err_segregation_violation(msg: str = "Custodian cannot approve their own participant-initiated request") -> APIError:
    return APIError("ERR_SEGREGATION_VIOLATION", msg, 403)


def err_contribution_cap_exceeded(msg: str = "Contribution would exceed the applicable annual cap") -> APIError:
    return APIError("ERR_CONTRIBUTION_CAP_EXCEEDED", msg, 422)


def err_catchup_age_ineligible(msg: str = "Participant is not age-eligible for catch-up contributions") -> APIError:
    return APIError("ERR_CATCHUP_AGE_INELIGIBLE", msg, 422)


def err_insufficient_balance(msg: str = "Distribution exceeds available balance") -> APIError:
    return APIError("ERR_INSUFFICIENT_BALANCE", msg, 422)


def err_rmd_amount_mismatch(msg: str = "RMD distribution amount does not equal the computed RMD") -> APIError:
    return APIError("ERR_RMD_AMOUNT_MISMATCH", msg, 422)


def err_backdoor_precondition_violated(
    msg: str = "Backdoor conversion preconditions not satisfied",
) -> APIError:
    return APIError("ERR_BACKDOOR_PRECONDITION_VIOLATED", msg, 422)


def err_rmd_period_closed(msg: str = "RMD for the requested tax_year is closed") -> APIError:
    return APIError("ERR_RMD_PERIOD_CLOSED", msg, 409)


def err_version_conflict(msg: str = "Supplied version does not match server version") -> APIError:
    return APIError("ERR_VERSION_CONFLICT", msg, 409)


def err_rmd_already_taken(msg: str = "An RMD-coded distribution already exists for this account and tax_year") -> APIError:
    return APIError("ERR_RMD_ALREADY_TAKEN", msg, 409)


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
        body = error_envelope("ERR_VALIDATION", "Malformed request")
        return jsonify(body), 400

    @app.errorhandler(415)
    def _handle_415(_exc):
        body = error_envelope("ERR_VALIDATION", "Unsupported media type")
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover — defensive
        body = error_envelope("ERR_VALIDATION", f"Unexpected server error: {exc}")
        return jsonify(body), 400
