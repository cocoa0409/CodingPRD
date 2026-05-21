"""Error catalogue and Flask error handlers (SCAFFOLD §1.6)."""

from __future__ import annotations

from typing import Optional

from flask import Flask, jsonify

from .envelope import build_meta


class ApiError(Exception):
    """Structured API error carrying error_id, http_status, and message."""

    def __init__(self, error_id: str, http_status: int, message: Optional[str] = None) -> None:
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error identifier constants — mirror SCAFFOLD §1.6.
ERR_MISSING_AUTH = "ERR_MISSING_AUTH"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_INPUT = "ERR_INVALID_INPUT"
ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
ERR_DUTY_EVENT_OUT_OF_ORDER = "ERR_DUTY_EVENT_OUT_OF_ORDER"
ERR_DRIVER_NOT_BOUND = "ERR_DRIVER_NOT_BOUND"
ERR_DRIVER_ALREADY_BOUND = "ERR_DRIVER_ALREADY_BOUND"
ERR_VEHICLE_ALREADY_BOUND = "ERR_VEHICLE_ALREADY_BOUND"
ERR_INVALID_DUTY_STATUS_FOR_BIND = "ERR_INVALID_DUTY_STATUS_FOR_BIND"
ERR_CROSS_CARRIER_BIND = "ERR_CROSS_CARRIER_BIND"
ERR_ELD_NOT_CERTIFIED = "ERR_ELD_NOT_CERTIFIED"
ERR_VEHICLE_MISMATCH = "ERR_VEHICLE_MISMATCH"
ERR_ELEVEN_HOUR_LIMIT_EXCEEDED = "ERR_ELEVEN_HOUR_LIMIT_EXCEEDED"
ERR_FOURTEEN_HOUR_WINDOW_EXCEEDED = "ERR_FOURTEEN_HOUR_WINDOW_EXCEEDED"
ERR_CYCLE_LIMIT_EXCEEDED = "ERR_CYCLE_LIMIT_EXCEEDED"
ERR_INSUFFICIENT_REST = "ERR_INSUFFICIENT_REST"
ERR_ANNOTATION_REQUIRED = "ERR_ANNOTATION_REQUIRED"
ERR_EXEMPTION_NOT_ACTIVE = "ERR_EXEMPTION_NOT_ACTIVE"
ERR_ODOMETER_DECREASED = "ERR_ODOMETER_DECREASED"
ERR_LOG_ALREADY_CERTIFIED = "ERR_LOG_ALREADY_CERTIFIED"
ERR_LOG_NOT_YET_CERTIFIABLE = "ERR_LOG_NOT_YET_CERTIFIABLE"
ERR_EDIT_WINDOW_EXPIRED = "ERR_EDIT_WINDOW_EXPIRED"
ERR_INVALID_VIOLATION_STATE = "ERR_INVALID_VIOLATION_STATE"


def make_error_body(error_id: str, message: str) -> dict:
    return {
        "meta": build_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        body = make_error_body(err.error_id, err.message)
        return jsonify(body), err.http_status

    @app.errorhandler(404)
    def handle_404(_err):
        body = make_error_body(ERR_NOT_FOUND, "Resource not found.")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(_err):
        body = make_error_body(ERR_NOT_FOUND, "Method not allowed.")
        return jsonify(body), 404

    @app.errorhandler(400)
    def handle_400(_err):
        body = make_error_body(ERR_INVALID_INPUT, "Malformed request body.")
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Avoid leaking 500s — re-shape into the envelope.
        body = make_error_body(ERR_INVALID_INPUT, f"Unhandled: {err}")
        return jsonify(body), 400
