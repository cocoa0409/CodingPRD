"""API errors and handlers."""
from __future__ import annotations

from flask import Flask, jsonify

from .envelope import error_envelope


class APIError(Exception):
    """Application error carrying error_id + HTTP status."""

    def __init__(self, error_id: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_auth_missing(message: str = "X-User-ID or X-User-Role missing/malformed") -> APIError:
    return APIError("ERR_AUTH_MISSING", message, 401)


def err_forbidden(message: str = "Role not authorized for this endpoint") -> APIError:
    return APIError("ERR_FORBIDDEN", message, 403)


def err_not_owner(message: str = "Acting user is not the owner of the resource") -> APIError:
    return APIError("ERR_NOT_OWNER", message, 403)


def err_not_found(message: str = "Resource not found") -> APIError:
    return APIError("ERR_NOT_FOUND", message, 404)


def err_reference_not_found(message: str = "Referenced resource does not exist") -> APIError:
    return APIError("ERR_REFERENCE_NOT_FOUND", message, 404)


def err_invalid_state(message: str = "Resource is not in a valid state for this transition") -> APIError:
    return APIError("ERR_INVALID_STATE", message, 409)


def err_dispute_already_exists(message: str = "Ride already has an open/approved dispute") -> APIError:
    return APIError("ERR_DISPUTE_ALREADY_EXISTS", message, 409)


def err_version_conflict(message: str = "Version mismatch") -> APIError:
    return APIError("ERR_VERSION_CONFLICT", message, 409)


def err_no_drivers_available(message: str = "No drivers available for assignment") -> APIError:
    return APIError("ERR_NO_DRIVERS_AVAILABLE", message, 409)


def err_not_airport_grid(message: str = "Grid is not an airport grid") -> APIError:
    return APIError("ERR_NOT_AIRPORT_GRID", message, 422)


def err_driver_not_in_grid(message: str = "Driver is not in the requested grid") -> APIError:
    return APIError("ERR_DRIVER_NOT_IN_GRID", message, 422)


def err_rush_hour_overlap(message: str = "Rush-hour window overlaps an existing active window") -> APIError:
    return APIError("ERR_RUSH_HOUR_OVERLAP", message, 422)


def err_quest_window_overlap(message: str = "Quest window overlaps an existing enrollment") -> APIError:
    return APIError("ERR_QUEST_WINDOW_OVERLAP", message, 422)


def err_refund_exceeds_fare(message: str = "requested_refund_cents exceeds Ride.final_fare_cents") -> APIError:
    return APIError("ERR_REFUND_EXCEEDS_FARE", message, 422)


def err_refund_exceeds_request(message: str = "approved_refund_cents exceeds requested_refund_cents") -> APIError:
    return APIError("ERR_REFUND_EXCEEDS_REQUEST", message, 422)


def err_invalid_input(message: str = "Invalid input") -> APIError:
    return APIError("ERR_INVALID_INPUT", message, 422)


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(APIError)
    def _handle_api_error(exc: APIError):
        body = error_envelope(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def _handle_404(_exc):
        body = error_envelope("ERR_NOT_FOUND", "Resource not found")
        return jsonify(body), 404

    @app.errorhandler(405)
    def _handle_405(_exc):
        body = error_envelope("ERR_NOT_FOUND", "Method not allowed")
        return jsonify(body), 404

    @app.errorhandler(400)
    def _handle_400(_exc):
        body = error_envelope("ERR_INVALID_INPUT", "Malformed request")
        return jsonify(body), 422

    @app.errorhandler(500)
    def _handle_500(exc):  # pragma: no cover
        body = error_envelope("ERR_INVALID_INPUT", f"Internal error: {exc}")
        return jsonify(body), 500
