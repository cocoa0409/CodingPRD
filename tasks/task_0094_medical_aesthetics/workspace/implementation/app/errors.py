"""Custom exception type and Flask error-handler registration."""
from __future__ import annotations

from typing import Any

from flask import Flask, jsonify

from .response import error_envelope


ERROR_HTTP_STATUS: dict[str, int] = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_INPUT": 400,
    "ERR_PAGINATION_OUT_OF_RANGE": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_CUSTOMER_UNDERAGE": 422,
    "ERR_ABSOLUTE_CONTRAINDICATION": 422,
    "ERR_SEGREGATION_VIOLATION": 422,
    "ERR_CONSENT_NOT_SIGNED": 422,
    "ERR_LOT_NUMBER_REQUIRED": 422,
    "ERR_DOCTOR_NOT_QUALIFIED": 422,
    "ERR_PROJECT_NOT_ON_SHELF": 422,
    "ERR_PROJECT_IN_USE": 409,
    "ERR_ANESTHESIA_REQUIREMENT_MISMATCH": 422,
    "ERR_ROOM_KIND_MISMATCH": 422,
    "ERR_DOCTOR_CONFLICT": 409,
    "ERR_NURSE_CONFLICT": 409,
    "ERR_ROOM_CONFLICT": 409,
    "ERR_EQUIPMENT_CONFLICT": 409,
    "ERR_ANESTHESIA_CONFLICT": 409,
    "ERR_CHECKIN_OUTSIDE_WINDOW": 422,
    "ERR_RESCHEDULE_LIMIT": 422,
    "ERR_PLAN_ITEMS_OUT_OF_RANGE": 422,
    "ERR_PLAN_STALE_REFERENCE": 409,
    "ERR_INVALID_INSTALLMENT_TERM": 422,
    "ERR_KYC_OR_CREDIT_FAIL": 422,
    "ERR_DOWNPAYMENT_OUT_OF_RANGE": 422,
    "ERR_PAYMENT_AMOUNT_INVALID": 422,
    "ERR_INSTALLMENT_ALREADY_EXISTS": 409,
}


class ApiError(Exception):
    """Raised anywhere in the codebase to propagate a structured error response."""

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
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def _handle_generic(exc):  # noqa: ANN001
        if isinstance(exc, ApiError):
            return _handle_api_error(exc)
        body = error_envelope(
            "ERR_INVALID_INPUT",
            f"Unhandled error: {exc.__class__.__name__}: {exc}",
        )
        return jsonify(body), 500
