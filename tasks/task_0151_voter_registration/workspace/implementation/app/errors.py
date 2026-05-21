"""Domain-specific errors and Flask handlers."""
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


# ----- canonical factories (one per error code from SCAFFOLD.errors) -----


def err_bad_request(message: str = "Malformed request") -> APIError:
    return APIError("ERR_BAD_REQUEST", message, 400)


def err_unauthenticated(message: str = "Missing or malformed authentication headers") -> APIError:
    return APIError("ERR_UNAUTHENTICATED", message, 401)


def err_forbidden(message: str = "Role is not permitted to perform this action") -> APIError:
    return APIError("ERR_FORBIDDEN", message, 403)


def err_forbidden_sod(message: str = "Segregation of duties violation") -> APIError:
    return APIError("ERR_FORBIDDEN_SOD", message, 403)


def err_not_found(message: str = "Resource not found") -> APIError:
    return APIError("ERR_NOT_FOUND", message, 404)


def err_invalid_state(message: str = "Entity is not in a state that permits this operation") -> APIError:
    return APIError("ERR_INVALID_STATE", message, 409)


def err_version_mismatch(message: str = "Optimistic concurrency mismatch") -> APIError:
    return APIError("ERR_VERSION_MISMATCH", message, 409)


def err_deadline_passed(message: str = "Operation attempted after applicable deadline") -> APIError:
    return APIError("ERR_DEADLINE_PASSED", message, 409)


def err_double_vote(message: str = "Voter has already cast a ballot for this election") -> APIError:
    return APIError("ERR_DOUBLE_VOTE", message, 409)


def err_party_locked(message: str = "Party affiliation is frozen after the registration deadline") -> APIError:
    return APIError("ERR_PARTY_LOCKED", message, 409)


def err_absentee_already_issued(message: str = "An absentee ballot already exists for this voter and election") -> APIError:
    return APIError("ERR_ABSENTEE_ALREADY_ISSUED", message, 409)


def err_voter_not_active(message: str = "Voter is not ACTIVE") -> APIError:
    return APIError("ERR_VOTER_NOT_ACTIVE", message, 409)


def err_return_late(message: str = "Absentee ballot received after ballot_return_deadline") -> APIError:
    return APIError("ERR_RETURN_LATE", message, 409)


def err_max_rounds(message: str = "Curing case has reached max_rounds") -> APIError:
    return APIError("ERR_MAX_ROUNDS_REACHED", message, 409)


def err_curing_in_progress(message: str = "A curing case is still open") -> APIError:
    return APIError("ERR_CURING_IN_PROGRESS", message, 409)


def err_machine_failure(message: str = "Machine failure: use ELECTION_DAY_PROVISIONAL") -> APIError:
    return APIError("ERR_MACHINE_FAILURE", message, 409)


def err_voter_has_ballot(message: str = "Voter has already cast a ballot") -> APIError:
    return APIError("ERR_VOTER_HAS_BALLOT", message, 409)


def err_tally_too_early(message: str = "Cannot tally before ballot_return_deadline") -> APIError:
    return APIError("ERR_TALLY_TOO_EARLY", message, 409)


def err_recount_required(message: str = "A recount must be completed before certification") -> APIError:
    return APIError("ERR_RECOUNT_REQUIRED", message, 409)


def err_recount_no_overturn(message: str = "Reconciled winner equals provisional winner") -> APIError:
    return APIError("ERR_RECOUNT_NO_OVERTURN", message, 409)


def err_no_precincts(message: str = "Election requires at least one precinct") -> APIError:
    return APIError("ERR_NO_PRECINCTS", message, 409)


def err_not_citizen(message: str = "Voter must attest citizenship") -> APIError:
    return APIError("ERR_NOT_CITIZEN", message, 422)


def err_under_age(message: str = "Voter is under 18 on election day") -> APIError:
    return APIError("ERR_UNDER_AGE", message, 422)


def err_residency_insufficient(message: str = "Voter has insufficient residency duration") -> APIError:
    return APIError("ERR_RESIDENCY_INSUFFICIENT", message, 422)


def err_no_precinct_match(message: str = "No precinct matches the voter's residency_address") -> APIError:
    return APIError("ERR_NO_PRECINCT_MATCH", message, 422)


def err_recount_petition_insufficient(message: str = "petition_count must be >= 100") -> APIError:
    return APIError("ERR_RECOUNT_PETITION_INSUFFICIENT", message, 422)


# ---------- Flask handlers ----------


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
        body = error_envelope("ERR_NOT_FOUND", "Method not allowed")
        return jsonify(body), 404

    @app.errorhandler(400)
    def _handle_400(_exc):
        body = error_envelope("ERR_BAD_REQUEST", "Malformed request")
        return jsonify(body), 400

    @app.errorhandler(500)
    def _handle_500(exc):  # pragma: no cover
        body = error_envelope("ERR_BAD_REQUEST", f"Internal error: {exc}")
        return jsonify(body), 500
