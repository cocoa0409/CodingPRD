"""Custom exception type and error-handler registration. PRD §5 + SCAFFOLD §1.6."""
from __future__ import annotations

from typing import Any

from flask import Flask, jsonify

from .response import error_envelope


ERROR_HTTP_STATUS: dict[str, int] = {
    "ERR_AUTH_REQUIRED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_DUPLICATE_CASE": 409,
    "ERR_DUPLICATE_BULLETIN": 409,
    "ERR_INSTITUTION_INACTIVE": 403,
    "ERR_TEST_RESULT_EXPIRED": 422,
    "ERR_ISOLATION_DATE_INVALID": 422,
    "ERR_FACILITY_AT_CAPACITY": 409,
    "ERR_RELEASE_NOT_ELIGIBLE": 422,
    "ERR_SELF_CONTACT": 422,
    "ERR_EVENT_TIME_INVALID": 422,
    "ERR_SUPPLY_INSUFFICIENT": 409,
    "ERR_DISPATCH_QUANTITY_MISMATCH": 422,
    "ERR_CONSUMPTION_EXCEEDS_DISPATCH": 422,
    "ERR_TIER_STALE": 422,
    "ERR_INVALID_CHANNELS": 422,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_INVALID_INPUT": 422,
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
        body = error_envelope("ERR_INVALID_INPUT", "Bad request.")
        return jsonify(body), 422

    @app.errorhandler(Exception)
    def _handle_generic(exc):  # noqa: ANN001
        body = error_envelope(
            "ERR_INVALID_INPUT",
            f"Unhandled error: {exc.__class__.__name__}: {exc}",
        )
        return jsonify(body), 500
