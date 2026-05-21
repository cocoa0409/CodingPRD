"""Error catalog and Flask error handlers (SCAFFOLD §1.6)."""

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


# Request shape / auth
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_OWNERSHIP_MISMATCH = "ERR_OWNERSHIP_MISMATCH"

# Existence
ERR_MEMBER_NOT_FOUND = "ERR_MEMBER_NOT_FOUND"
ERR_FLIGHT_NOT_FOUND = "ERR_FLIGHT_NOT_FOUND"
ERR_SEGMENT_NOT_FOUND = "ERR_SEGMENT_NOT_FOUND"
ERR_BOOKING_NOT_FOUND = "ERR_BOOKING_NOT_FOUND"
ERR_CERTIFICATE_NOT_FOUND = "ERR_CERTIFICATE_NOT_FOUND"
ERR_UPGRADE_REQUEST_NOT_FOUND = "ERR_UPGRADE_REQUEST_NOT_FOUND"
ERR_STATUS_MATCH_REQUEST_NOT_FOUND = "ERR_STATUS_MATCH_REQUEST_NOT_FOUND"

# State
ERR_BOOKING_NOT_HOLDABLE = "ERR_BOOKING_NOT_HOLDABLE"
ERR_BOOKING_NOT_CANCELLABLE = "ERR_BOOKING_NOT_CANCELLABLE"
ERR_SEGMENT_NOT_FLYABLE = "ERR_SEGMENT_NOT_FLYABLE"
ERR_SEGMENT_NOT_REFUNDABLE = "ERR_SEGMENT_NOT_REFUNDABLE"
ERR_UPGRADE_NOT_WAITLISTED = "ERR_UPGRADE_NOT_WAITLISTED"
ERR_STATUS_MATCH_NOT_PENDING = "ERR_STATUS_MATCH_NOT_PENDING"
ERR_STATUS_MATCH_NOT_APPROVED = "ERR_STATUS_MATCH_NOT_APPROVED"
ERR_CERTIFICATE_NOT_USABLE = "ERR_CERTIFICATE_NOT_USABLE"
ERR_FLIGHT_NOT_BOOKABLE = "ERR_FLIGHT_NOT_BOOKABLE"
ERR_FLIGHT_NOT_CANCELLABLE = "ERR_FLIGHT_NOT_CANCELLABLE"

# Cross-entity referential
ERR_MEMBER_TIER_INELIGIBLE = "ERR_MEMBER_TIER_INELIGIBLE"
ERR_TARGET_CABIN_NOT_UPGRADE = "ERR_TARGET_CABIN_NOT_UPGRADE"
ERR_BOOKING_FLIGHT_MISMATCH = "ERR_BOOKING_FLIGHT_MISMATCH"

# Temporal
ERR_CERTIFICATE_EXPIRED = "ERR_CERTIFICATE_EXPIRED"
ERR_STATUS_MATCH_COOLING_OFF = "ERR_STATUS_MATCH_COOLING_OFF"
ERR_STATUS_MATCH_ALREADY_ACTIVE = "ERR_STATUS_MATCH_ALREADY_ACTIVE"
ERR_HELD_UNTIL_PASSED = "ERR_HELD_UNTIL_PASSED"

# Constraint / inventory / uniqueness
ERR_UPGRADE_INVENTORY_EXHAUSTED = "ERR_UPGRADE_INVENTORY_EXHAUSTED"
ERR_IDEMPOTENCY_CONFLICT = "ERR_IDEMPOTENCY_CONFLICT"
ERR_EMAIL_CONFLICT = "ERR_EMAIL_CONFLICT"
ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"

# Fiscal
ERR_INSUFFICIENT_POINTS = "ERR_INSUFFICIENT_POINTS"
ERR_GIFT_DAILY_CAP_EXCEEDED = "ERR_GIFT_DAILY_CAP_EXCEEDED"
ERR_GIFT_BELOW_MINIMUM = "ERR_GIFT_BELOW_MINIMUM"

# Safety
ERR_MEMBER_FROZEN = "ERR_MEMBER_FROZEN"
ERR_MEMBER_CLOSED = "ERR_MEMBER_CLOSED"


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
        body = make_error_body(ERR_INVALID_REQUEST, "Route not found.")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(_err):
        body = make_error_body(ERR_INVALID_REQUEST, "Method not allowed.")
        return jsonify(body), 405

    @app.errorhandler(400)
    def handle_400(_err):
        body = make_error_body(ERR_INVALID_REQUEST, "Malformed request body.")
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        body = make_error_body(ERR_INVALID_REQUEST, f"Unhandled: {err}")
        return jsonify(body), 400
