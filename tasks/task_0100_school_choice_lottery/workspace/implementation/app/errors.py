"""Error catalog and Flask error handlers."""
from flask import Flask, jsonify

from .responses import error_response


# Map of error_id -> HTTP status code (from PRD §5 / SCAFFOLD §1.6).
ERROR_CATALOG = {
    "ERR_AUTH_MISSING": 401,
    "ERR_AUTH_INVALID_ROLE": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 422,
    "ERR_VERSION_MISMATCH": 409,
    "ERR_REGISTRATION_WINDOW_CLOSED": 409,
    "ERR_INVALID_STATE_FOR_TRANSITION": 409,
    "ERR_LOTTERY_NOT_READY": 409,
    "ERR_LOTTERY_ALREADY_DRAWN": 409,
    "ERR_LOTTERY_SEED_MISSING": 422,
    "ERR_TRANSFER_NOT_APPROVED": 422,
    "ERR_DISTRICT_NO_TRANSFERS": 422,
    "ERR_DISTRICT_CAPACITY_EXCEEDED": 409,
    "ERR_GRADE_MISMATCH": 422,
    "ERR_GRADE_NOT_OFFERED": 422,
    "ERR_DUPLICATE_CHOICE_RANK": 422,
    "ERR_OFFER_EXPIRED": 409,
    "ERR_TOO_MANY_CHOICES": 422,
    "ERR_STUDENT_ALREADY_ACCEPTED": 409,
    "ERR_SEAT_NOT_AVAILABLE": 409,
    "ERR_SEATS_BELOW_COMMITTED": 422,
    "ERR_WITHDRAW_GRACE_PASSED": 409,
    "ERR_VALIDATION": 422,
}


class APIError(Exception):
    """Custom exception that carries an error_id, message, and HTTP status."""

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
        # Surface unexpected errors as ERR_VALIDATION so tests get structured output.
        body, status = error_response("ERR_VALIDATION", f"Unexpected error: {type(e).__name__}: {e}", 422)
        return jsonify(body), status
