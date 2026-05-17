"""Error catalog (SCAFFOLD §1.6 / PRD §5) and Flask handlers."""
from flask import Flask, jsonify

from .responses import error_response


# Map of error_id -> HTTP status code, sourced directly from SCAFFOLD §1.6.
ERROR_CATALOG = {
    # Auth / access
    "ERR_AUTH_MISSING": 401,
    "ERR_FORBIDDEN": 403,
    # Existence
    "ERR_NOT_FOUND": 404,
    # State
    "ERR_OASIS_NOT_DRAFT": 409,
    "ERR_OASIS_NOT_LOCKED": 409,
    "ERR_EPISODE_NOT_OPEN": 409,
    "ERR_VISIT_NOT_SCHEDULED": 409,
    "ERR_MILEAGE_VISIT_NOT_COMPLETED": 409,
    # Safety / compliance
    "ERR_CLINICIAN_LICENSE_EXPIRED": 422,
    "ERR_CLINICIAN_NOT_AVAILABLE": 422,
    "ERR_DISCIPLINE_MISMATCH": 422,
    "ERR_RECERT_WINDOW_VIOLATION": 422,
    # Temporal / referential
    "ERR_VISIT_OUTSIDE_EPISODE": 422,
    "ERR_VISIT_TIME_INVALID": 422,
    "ERR_CLINICIAN_DOUBLE_BOOKED": 409,
    "ERR_OASIS_ALREADY_USED": 409,
    "ERR_PATIENT_HAS_OPEN_EPISODE": 409,
    # Fiscal / quota
    "ERR_HHA_HOURS_EXCEEDED": 422,
    # Constraints
    "ERR_MILEAGE_NOT_POSITIVE": 422,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_CLOCK_BACKWARDS": 422,
    # Generic validation fallback (request shape, JSON parsing, type mismatch).
    "ERR_VALIDATION": 422,
}


class APIError(Exception):
    """Custom exception carrying error_id, message, and HTTP status."""

    def __init__(self, error_id: str, message: str = "", http_status: int = None):
        super().__init__(message)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status if http_status is not None else ERROR_CATALOG.get(error_id, 400)


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):
        body, status = error_response(err.error_id, err.message, err.http_status)
        return jsonify(body), status

    @app.errorhandler(404)
    def handle_404(_e):
        body, status = error_response("ERR_NOT_FOUND", "Resource not found", 404)
        return jsonify(body), status

    @app.errorhandler(405)
    def handle_405(_e):
        body, status = error_response("ERR_NOT_FOUND", "Method not allowed", 404)
        return jsonify(body), status

    @app.errorhandler(400)
    def handle_400(_e):
        body, status = error_response("ERR_VALIDATION", "Bad request", 422)
        return jsonify(body), status

    @app.errorhandler(Exception)
    def handle_unexpected(e: Exception):
        body, status = error_response(
            "ERR_VALIDATION", f"Unexpected error: {type(e).__name__}: {e}", 422
        )
        return jsonify(body), status
