"""Custom exception type and Flask error-handler registration."""
from __future__ import annotations

from typing import Any

from flask import Flask, jsonify

from .response import error_envelope


# Mapping of error_id -> http status (per scaffold §1.6 / PRD §5)
ERROR_HTTP_STATUS: dict[str, int] = {
    "ERR_AUTH_MISSING": 401,
    "ERR_AUTH_INVALID_ROLE": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_REGISTRATION_NOT_OPEN": 409,
    "ERR_REGISTRATION_DEADLINE_PASSED": 409,
    "ERR_DUPLICATE_TEAM_NAME": 409,
    "ERR_ROSTER_LOCKED": 409,
    "ERR_ROSTER_INCOMPLETE": 422,
    "ERR_PLAYER_UNDERAGE": 422,
    "ERR_REGION_MISMATCH": 422,
    "ERR_TEAM_RANKING_INSUFFICIENT": 422,
    "ERR_IDENTITY_NOT_VERIFIED": 422,
    "ERR_INVALID_CONTRACT_TERM": 422,
    "ERR_NO_SIGNATORIES": 422,
    "ERR_WRONG_SIGNATORY": 422,
    "ERR_TEAM_NOT_ELIGIBLE": 409,
    "ERR_ENTRY_FEE_INSUFFICIENT": 402,
    "ERR_TOURNAMENT_FULL": 409,
    "ERR_INSUFFICIENT_TEAMS": 422,
    "ERR_PRIZE_TIER_SUM_MISMATCH": 422,
    "ERR_TOURNAMENT_NOT_COMPLETED": 409,
    "ERR_PRIZE_FINAL_MISMATCH": 409,
    "ERR_PRIZE_POOL_INVARIANT": 409,
    "ERR_PRIZE_POOL_NOT_FINALIZED": 409,
    "ERR_PAYOUT_BELOW_FLOOR": 422,
    "ERR_MATCH_NOT_IN_WINDOW": 409,
    "ERR_MATCH_TIME_CONFLICT": 409,
    "ERR_REFEREE_CERT_EXPIRED": 403,
    "ERR_REFEREE_DOUBLE_BOOKED": 409,
    "ERR_DRAFT_STEP_OUT_OF_ORDER": 422,
    "ERR_DRAFT_STEP_TAKEN": 409,
    "ERR_DUPLICATE_INCIDENT": 409,
    "ERR_FINE_AMOUNT_REQUIRED": 422,
    "ERR_APPEAL_LIMIT_REACHED": 409,
    "ERR_APPEAL_WINDOW_CLOSED": 409,
    "ERR_WINDOW_CLOSED": 409,
    "ERR_COOLING_OFF_ACTIVE": 409,
    "ERR_CONTRACT_NOT_ACTIVE": 409,
    "ERR_MATCHES_INCOMPLETE": 409,
    "ERR_APPEAL_DECISION_REQUIRED": 422,
    "ERR_BAD_REQUEST": 400,
}


class ApiError(Exception):
    """Raised anywhere in the codebase to propagate a structured error response."""

    def __init__(self, error_id: str, message: str | None = None, http_status: int | None = None) -> None:
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status if http_status is not None else ERROR_HTTP_STATUS.get(error_id, 400)
        super().__init__(f"{error_id}: {self.message}")


def _default_message(error_id: str) -> str:
    return error_id.replace("ERR_", "").replace("_", " ").lower().capitalize() + "."


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError) -> Any:
        body = error_envelope(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def _handle_404(_exc):
        body = error_envelope("ERR_NOT_FOUND", "Resource not found.")
        return jsonify(body), 404

    @app.errorhandler(405)
    def _handle_405(_exc):
        body = error_envelope("ERR_NOT_FOUND", "Method not allowed.")
        return jsonify(body), 404

    @app.errorhandler(400)
    def _handle_400(_exc):
        body = error_envelope("ERR_BAD_REQUEST", "Bad request.")
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def _handle_generic(exc):  # noqa: ANN001
        # Last-ditch — surface a 500 with our envelope so the test harness gets a JSON body.
        body = error_envelope("ERR_BAD_REQUEST", f"Unhandled error: {exc.__class__.__name__}: {exc}")
        return jsonify(body), 500
