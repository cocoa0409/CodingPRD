"""Custom exception type and Flask error-handler registration. PRD §5."""
from __future__ import annotations

from typing import Any

from flask import Flask, jsonify

from .response import error_envelope


ERROR_HTTP_STATUS: dict[str, int] = {
    "ERR_AUTH_REQUIRED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_SOD_VIOLATION": 403,
    "ERR_BORROWER_NOT_FOUND": 404,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_LOAN_NOT_FOUND": 404,
    "ERR_BAD_DATE_WINDOW": 400,
    "ERR_AMOUNT_INVALID": 400,
    "ERR_PAGINATION_INVALID": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_PLAN_CONFLICT": 409,
    "ERR_PLAN_LOAN_INELIGIBLE": 422,
    "ERR_AGI_NOT_CERTIFIED": 422,
    "ERR_VETERAN_INELIGIBLE": 422,
    "ERR_PSLF_NO_EMPLOYMENT_EVIDENCE": 422,
    "ERR_PSLF_INSUFFICIENT_PAYMENTS": 422,
    "ERR_FORBEARANCE_CAP_EXCEEDED": 422,
    "ERR_PLUS_INELIGIBLE_FOR_IN_SCHOOL": 422,
    "ERR_REHAB_ALREADY_USED": 422,
    "ERR_INVALID_INPUT": 400,
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
        body = error_envelope("ERR_RESOURCE_NOT_FOUND", "Resource not found.")
        return jsonify(body), 404

    @app.errorhandler(405)
    def _handle_405(_exc):
        body = error_envelope("ERR_RESOURCE_NOT_FOUND", "Method not allowed.")
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
