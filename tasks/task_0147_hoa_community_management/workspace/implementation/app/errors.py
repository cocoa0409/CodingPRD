"""Domain-specific errors and their handlers."""
from __future__ import annotations

from flask import Flask, jsonify

from .envelope import error_envelope


class APIError(Exception):
    """Application error carrying error_id + HTTP status."""

    def __init__(self, error_id: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# ---------- Specific factories (encourage consistent messages) ----------


def err_unauthenticated(message: str = "Missing or malformed authentication headers") -> APIError:
    return APIError("ERR_UNAUTHENTICATED", message, 401)


def err_forbidden(message: str = "Role is not permitted to perform this action") -> APIError:
    return APIError("ERR_FORBIDDEN", message, 403)


def err_not_found(message: str = "Resource not found") -> APIError:
    return APIError("ERR_NOT_FOUND", message, 404)


def err_invalid_state(message: str = "Entity is not in a state that permits this operation") -> APIError:
    return APIError("ERR_INVALID_STATE", message, 409)


def err_version_conflict(message: str = "Optimistic concurrency mismatch") -> APIError:
    return APIError("ERR_VERSION_CONFLICT", message, 409)


def err_share_factor(message: str = "Sum of unit share_factor must equal exactly 1.0000") -> APIError:
    return APIError("ERR_SHARE_FACTOR_SUM_INVALID", message, 422)


def err_lien_cooling_off(message: str = "Lien notice cooling-off period (30 days) has not elapsed") -> APIError:
    return APIError("ERR_LIEN_COOLING_OFF", message, 409)


def err_not_on_acc(message: str = "Voter does not hold a seat on the 3-seat ACC subset") -> APIError:
    return APIError("ERR_NOT_ON_ACC", message, 403)


def err_voter_ineligible(message: str = "Voter is not eligible") -> APIError:
    return APIError("ERR_VOTER_INELIGIBLE", message, 403)


def err_voting_closed(message: str = "Voting is not open at this instant") -> APIError:
    return APIError("ERR_VOTING_CLOSED", message, 409)


def err_duplicate_ballot(message: str = "Duplicate ballot for this voter in this election") -> APIError:
    return APIError("ERR_DUPLICATE_BALLOT", message, 409)


def err_levy_too_small(message: str = "total_levy_cents must be >= 100") -> APIError:
    return APIError("ERR_LEVY_TOO_SMALL", message, 422)


def err_amount_invalid(message: str = "Payment amount must be > 0") -> APIError:
    return APIError("ERR_AMOUNT_INVALID", message, 422)


def err_owner_delinquent(message: str = "Owner has outstanding overdue balance") -> APIError:
    return APIError("ERR_OWNER_DELINQUENT", message, 409)


def err_reserve_posture(message: str = "Reserve study posture blocks new ACC reviews") -> APIError:
    return APIError("ERR_RESERVE_POSTURE_BLOCKS_ACC", message, 409)


def err_segregation(message: str = "Segregation of duties violated") -> APIError:
    return APIError("ERR_SEGREGATION_OF_DUTIES", message, 403)


def err_nomination_closed(message: str = "Nomination window is not open") -> APIError:
    return APIError("ERR_NOMINATION_CLOSED", message, 409)


def err_resolution_target(message: str = "Resolution subject does not match target state/type") -> APIError:
    return APIError("ERR_RESOLUTION_TARGET_INVALID", message, 422)


def err_time_travel(message: str = "target_timestamp must be >= current clock") -> APIError:
    return APIError("ERR_TIME_TRAVEL", message, 422)


# ---------- Handlers ----------


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
        body = error_envelope("ERR_INVALID_STATE", "Malformed request")
        return jsonify(body), 409

    @app.errorhandler(500)
    def _handle_500(exc):  # pragma: no cover - defensive
        body = error_envelope("ERR_INVALID_STATE", f"Internal error: {exc}")
        return jsonify(body), 500
