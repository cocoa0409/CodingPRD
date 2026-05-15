"""Custom exception and Flask error handlers."""
from __future__ import annotations

from flask import Flask, jsonify, request

from app.response import error_envelope


class APIError(Exception):
    def __init__(self, error_id: str, message: str = "", http_status: int = 400):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status


# Convenience preset for the catalog: maps error_id -> http_status. Kept in sync with PRD §5.
ERROR_STATUS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_PET_NOT_FOUND": 404,
    "ERR_SUBSCRIPTION_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_RECIPE_NOT_FOUND": 404,
    "ERR_ADJUSTMENT_NOT_FOUND": 404,
    "ERR_WAREHOUSE_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_FEEDBACK_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_FEEDBACK_PAYLOAD": 422,
    "ERR_INVALID_PET_LIST": 422,
    "ERR_INVALID_CANCEL_REASON": 400,
    "ERR_INVALID_PAUSE_WINDOW": 422,
    "ERR_INVALID_SUBSCRIPTION_STATE": 409,
    "ERR_INVALID_ORDER_STATE": 409,
    "ERR_INVALID_ADJUSTMENT_STATE": 409,
    "ERR_PET_NOT_ACTIVE": 409,
    "ERR_PAUSE_BLOCKED_IN_TRANSIT": 409,
    "ERR_MODIFICATION_DEADLINE_PASSED": 409,
    "ERR_PAUSE_WINDOW_OVERLAP": 409,
    "ERR_ADDRESS_VERIFICATION_FAILED": 422,
    "ERR_ADDRESS_NOT_VERIFIED": 422,
    "ERR_ALLERGEN_PROHIBITED": 422,
    "ERR_VET_PRESCRIBED_REQUIRED": 422,
    "ERR_RECIPE_NOT_ELIGIBLE": 422,
    "ERR_ROTATION_VIOLATION": 422,
    "ERR_NO_RECIPE_AVAILABLE": 422,
    "ERR_NO_WAREHOUSE_AVAILABLE": 409,
    "ERR_WAREHOUSE_CAPACITY_EXCEEDED": 409,
    "ERR_INSUFFICIENT_INVENTORY": 409,
    "ERR_VERSION_CONFLICT": 409,
}


def api_error(error_id: str, message: str = "") -> APIError:
    return APIError(error_id, message or error_id, ERROR_STATUS.get(error_id, 400))


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):
        body, status = error_envelope(err.error_id, err.message, err.http_status)
        return jsonify(body), status

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route → treat as malformed request rather than catalog 404
        body, status = error_envelope(
            "ERR_INVALID_REQUEST",
            f"Route not found: {request.path}",
            400,
        )
        return jsonify(body), status

    @app.errorhandler(405)
    def handle_405(err):
        body, status = error_envelope(
            "ERR_INVALID_REQUEST",
            f"Method not allowed: {request.method} {request.path}",
            400,
        )
        return jsonify(body), status

    @app.errorhandler(400)
    def handle_400(err):
        body, status = error_envelope("ERR_INVALID_REQUEST", "Malformed request", 400)
        return jsonify(body), status

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Re-raise APIError so the dedicated handler runs
        if isinstance(err, APIError):
            return handle_api_error(err)
        body, status = error_envelope("ERR_INVALID_REQUEST", str(err), 400)
        return jsonify(body), status
