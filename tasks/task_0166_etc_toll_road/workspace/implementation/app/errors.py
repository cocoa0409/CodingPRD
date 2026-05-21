"""Custom error class and Flask error handlers."""
from flask import Flask, jsonify

from .responses import error_envelope


class ApiError(Exception):
    """Raised to short-circuit a request with a structured error response."""

    def __init__(self, error_id: str, http_status: int, message: str = "") -> None:
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Canonical default messages for each known error id.
DEFAULT_MESSAGES = {
    "ERR_MISSING_AUTH": "X-User-ID and X-User-Role headers are required.",
    "ERR_INVALID_ROLE": "X-User-Role is not a recognized role.",
    "ERR_FORBIDDEN": "The caller is not permitted to perform this operation.",
    "ERR_NOT_FOUND": "The requested resource was not found.",
    "ERR_DUPLICATE_RESOURCE": "A resource with the supplied identifier already exists.",
    "ERR_VEHICLE_ALREADY_BOUND": "The vehicle already has an active transponder bound.",
    "ERR_INVALID_STATE": "The resource is not in a valid state for the requested operation.",
    "ERR_ACCOUNT_NOT_ACTIVE": "Account is not ACTIVE.",
    "ERR_VEHICLE_BLOCKED": "Vehicle is BLOCKED.",
    "ERR_INSUFFICIENT_FUNDS_ON_PLATE_BILL": "Plate-billed event without auto-reload would overdraw the balance.",
    "ERR_HOV_FRAUD_RECORDED": "HOV claim could not be substantiated; violation recorded.",
    "ERR_DUPLICATE_TOLL_EVENT": "A toll event for this gantry/minute/vehicle has already been recorded.",
    "ERR_VOID_WINDOW_EXPIRED": "The 24-hour void window has expired.",
    "ERR_DISPUTE_LIMIT_REACHED": "Fine has reached the dispute limit.",
    "ERR_VERSION_CONFLICT": "Resource version does not match the request.",
    "ERR_RELOAD_ALREADY_RUNNING": "An auto-reload has already credited this account this minute.",
    "ERR_INTEROP_POLICY_AMBIGUOUS": "More than one InteropPolicy row matched the lookup.",
    "ERR_INVALID_RELOAD_AMOUNT": "Manual reload amount must be between 100 and 50000 cents.",
    "ERR_ACCOUNT_HAS_OBLIGATIONS": "Account has outstanding fines or active transponders and cannot be closed.",
    "ERR_VALIDATION": "Request validation failed.",
}


def raise_api_error(error_id: str, message: str = "", http_status: int = 0) -> None:
    """Convenience function used by services to raise structured errors."""
    if http_status == 0:
        http_status = _default_status_for(error_id)
    if not message:
        message = DEFAULT_MESSAGES.get(error_id, error_id)
    raise ApiError(error_id=error_id, http_status=http_status, message=message)


def _default_status_for(error_id: str) -> int:
    mapping = {
        "ERR_MISSING_AUTH": 401,
        "ERR_INVALID_ROLE": 401,
        "ERR_FORBIDDEN": 403,
        "ERR_NOT_FOUND": 404,
        "ERR_INTEROP_POLICY_AMBIGUOUS": 422,
        "ERR_INVALID_RELOAD_AMOUNT": 422,
        "ERR_VALIDATION": 422,
    }
    return mapping.get(error_id, 409)


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError):
        body = error_envelope(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def _handle_404(_):
        body = error_envelope("ERR_NOT_FOUND", DEFAULT_MESSAGES["ERR_NOT_FOUND"])
        return jsonify(body), 404

    @app.errorhandler(405)
    def _handle_405(_):
        body = error_envelope("ERR_NOT_FOUND", "Method not allowed for this path.")
        return jsonify(body), 404

    @app.errorhandler(400)
    def _handle_400(_):
        body = error_envelope("ERR_VALIDATION", "Malformed request body.")
        return jsonify(body), 422

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        if isinstance(exc, ApiError):
            body = error_envelope(exc.error_id, exc.message)
            return jsonify(body), exc.http_status
        body = error_envelope("ERR_VALIDATION", "Unexpected error: " + str(exc))
        return jsonify(body), 422
