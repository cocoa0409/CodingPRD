"""Custom exception type and Flask error-handler registration (PRD §5)."""
from __future__ import annotations

from typing import Any

from flask import Flask, jsonify

from .response import error_envelope


ERROR_HTTP_STATUS: dict[str, int] = {
    "ERR_AUTH_MISSING": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_INPUT": 400,
    "ERR_PAGINATION_OUT_OF_RANGE": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_DUPLICATE_CODING_RECORD": 409,
    "ERR_DUPLICATE_WRITE_OFF": 409,
    "ERR_POLICY_PATIENT_MISMATCH": 422,
    "ERR_PLAN_YEAR_EXPIRED": 422,
    "ERR_INVALID_ICD10": 422,
    "ERR_INVALID_CPT": 422,
    "ERR_CODING_CPT_MISMATCH": 422,
    "ERR_ALLOWED_EXCEEDS_CHARGES": 422,
    "ERR_INVALID_CLEARANCE_PAYLOAD": 422,
    "ERR_CHARGES_NOT_READY": 422,
    "ERR_WRITE_OFF_TOO_EARLY": 422,
    "ERR_WRITE_OFF_NO_BALANCE": 422,
    "ERR_PAYMENT_AMOUNT_INVALID": 422,
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
