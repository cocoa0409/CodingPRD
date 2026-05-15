"""Custom exception type and Flask error-handler registration. PRD §5, scaffold §1.6."""
from __future__ import annotations

from typing import Any

from flask import Flask, jsonify

from .response import error_envelope


ERROR_HTTP_STATUS: dict[str, int] = {
    "ERR_AUTH_MISSING": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_FILING_ALREADY_EXISTS": 409,
    "ERR_SETTLEMENT_ALREADY_ADVANCED": 409,
    "ERR_SETTLEMENT_HAS_ADVANCE": 409,
    "ERR_DOC_INCOMPLETE": 409,
    "ERR_DOC_INCONSISTENT": 409,
    "ERR_DOC_AUTHENTICITY_FLAGGED": 409,
    "ERR_DOC_MISSING_LICENSE": 409,
    "ERR_DOC_MISSING_DG": 409,
    "ERR_DECLARED_VALUE_FLAGGED": 409,
    "ERR_MANIFEST_MISMATCH": 409,
    "ERR_AGREEMENT_NOT_ACTIVE": 409,
    "ERR_AGREEMENT_VERSION_DRIFT": 409,
    "ERR_AGREEMENT_HAS_OPEN_DECLARATIONS": 409,
    "ERR_AMENDMENT_CAP_REACHED": 409,
    "ERR_INSPECTION_REJECTION_NOT_AMENDABLE": 409,
    "ERR_QUERY_DEADLINE_PASSED": 409,
    "ERR_SERVICE_OUT_OF_SCOPE": 409,
    "ERR_FEE_SCHEDULE_INVALID": 422,
    "ERR_SETTLEMENT_ZERO_AMOUNT": 409,
    "ERR_BANK_AMOUNT_MISMATCH": 422,
    "ERR_INVALID_INPUT": 422,
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
        return jsonify(body), 422

    @app.errorhandler(Exception)
    def _handle_generic(exc):  # noqa: ANN001
        body = error_envelope(
            "ERR_INVALID_INPUT",
            f"Unhandled error: {exc.__class__.__name__}: {exc}",
        )
        return jsonify(body), 500
