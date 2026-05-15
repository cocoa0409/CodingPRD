"""Custom exception type and error-handler registration. PRD §5 / SCAFFOLD §1.6."""
from __future__ import annotations

from typing import Any

from flask import Flask, jsonify

from .response import error_envelope


ERROR_HTTP_STATUS: dict[str, int] = {
    "ERR_AUTH_MISSING": 401,
    "ERR_AUTH_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_DUPLICATE": 409,
    "ERR_BIDDER_NOT_ACTIVE": 403,
    "ERR_STATUTORY_NOTICE_INSUFFICIENT": 422,
    "ERR_WINNER_DISQUALIFIED": 422,
    "ERR_INSPECTION_OVERLAPS_AUCTION": 422,
    "ERR_INSPECTION_WINDOW_CONFLICT": 409,
    "ERR_HANDOVER_AGENCY_BUSY": 409,
    "ERR_BID_NOT_ABOVE_HIGH": 422,
    "ERR_BID_AT_OR_ABOVE_CAP": 422,
    "ERR_DEPOSIT_NOT_PAID": 422,
    "ERR_PARTIAL_PAYMENT_REJECTED": 422,
    "ERR_DEPOSIT_DEADLINE_PASSED": 422,
    "ERR_TENANCY_NOT_CLEARED": 422,
    "ERR_REAUCTION_LIMIT_REACHED": 409,
    "ERR_NO_VALID_BIDS": 422,
    "ERR_NO_ELIGIBLE_SECOND_BIDDER": 422,
    "ERR_PAYMENT_FORFEITED": 409,
    "ERR_DEPOSIT_ALREADY_REFUNDED": 409,
    "ERR_DEPOSIT_DUPLICATE": 409,
}


class ApiError(Exception):
    def __init__(
        self,
        error_id: str,
        message: str | None = None,
        http_status: int | None = None,
    ) -> None:
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = (
            http_status if http_status is not None else ERROR_HTTP_STATUS.get(error_id, 422)
        )
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
        body = error_envelope("ERR_VALIDATION", "Bad request.")
        return jsonify(body), 422

    @app.errorhandler(Exception)
    def _handle_generic(exc):  # noqa: ANN001
        body = error_envelope(
            "ERR_VALIDATION",
            f"Unhandled error: {exc.__class__.__name__}: {exc}",
        )
        return jsonify(body), 500
