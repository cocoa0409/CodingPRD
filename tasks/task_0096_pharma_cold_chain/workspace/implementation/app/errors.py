"""Custom exception type and Flask error-handler registration."""
from __future__ import annotations

from typing import Any

from flask import Flask, jsonify

from .response import error_envelope


ERROR_HTTP_STATUS: dict[str, int] = {
    # Auth
    "ERR_AUTH_MISSING_ROLE": 401,
    "ERR_AUTH_MISSING_USER": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_SOD_VIOLATION": 403,
    # Existence
    "ERR_NOT_FOUND": 404,
    # State preconditions
    "ERR_RECEIPT_NOT_PENDING": 409,
    "ERR_RECEIPT_NOT_INSPECTED": 409,
    "ERR_RECEIPT_NOT_QUARANTINED": 409,
    "ERR_SHIPMENT_STATE_INVALID": 409,
    "ERR_RECALL_NOT_DRAFT": 409,
    "ERR_RECALL_STATE_INVALID": 409,
    "ERR_DEVIATION_STATE_INVALID": 409,
    "ERR_CAPA_STATE_INVALID": 409,
    "ERR_BIN_UNAVAILABLE": 409,
    # Cold-chain safety
    "ERR_ZONE_FROZEN": 409,
    "ERR_UNQUALIFIED_SUPPLIER": 422,
    "ERR_UNQUALIFIED_PRODUCT": 422,
    "ERR_EXPIRED_LOT": 422,
    "ERR_TEMP_PRECHECK_FAIL": 422,
    "ERR_LOGGER_DATA_INVALID": 422,
    # Business constraints
    "ERR_PACKAGING_MISMATCH": 422,
    "ERR_SEGREGATION_VIOLATION": 422,
    "ERR_FEFO_VIOLATION": 422,
    "ERR_NO_FEFO_LOT": 422,
    "ERR_NO_ELIGIBLE_BIN": 422,
    "ERR_BIN_CAPACITY_EXCEEDED": 422,
    "ERR_ZONE_CAPACITY_EXCEEDED": 422,
    "ERR_QUANTITY_INVALID": 422,
    "ERR_INSUFFICIENT_STOCK": 409,
    # Business referential / temporal
    "ERR_RECALL_SCOPE_EMPTY": 422,
    "ERR_RETURN_SCOPE_INVALID": 422,
    "ERR_TEMP_EVENT_TIME_INVALID": 422,
    "ERR_RECALL_DEADLINE_INVALID": 422,
    # OCC + generic
    "ERR_VERSION_CONFLICT": 409,
    "ERR_VALIDATION_FAILED": 422,
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
        body = error_envelope("ERR_VALIDATION_FAILED", "Bad request.")
        return jsonify(body), 422

    @app.errorhandler(Exception)
    def _handle_generic(exc):  # noqa: ANN001
        if isinstance(exc, ApiError):
            return _handle_api_error(exc)
        body = error_envelope(
            "ERR_VALIDATION_FAILED",
            f"Unhandled error: {exc.__class__.__name__}: {exc}",
        )
        return jsonify(body), 500
