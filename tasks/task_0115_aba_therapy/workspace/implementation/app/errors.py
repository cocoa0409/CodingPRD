"""Error catalog (SCAFFOLD §1.6 / PRD §5) and Flask handlers."""
from flask import Flask, jsonify

from .responses import error_response


# Map of error_id -> HTTP status code (per PRD §5 catalog).
ERROR_CATALOG = {
    "ERR_AUTH_REQUIRED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_THERAPIST_OF_RECORD": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_SESSION_NOT_COMPLETED": 409,
    "ERR_SESSION_THERAPIST_OVERLAP": 409,
    "ERR_PARENT_TRAINING_BUFFER": 409,
    "ERR_TREATMENT_PLAN_CONFLICT": 409,
    "ERR_CLAIM_STATE_INVALID": 409,
    "ERR_RENEWAL_CONFLICT": 409,
    "ERR_SESSION_ALREADY_CLAIMED": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_SUPERVISION_RATIO_BREACH": 422,
    "ERR_PLAN_RATIO_INSUFFICIENT": 422,
    "ERR_SESSION_AUTH_MISMATCH": 422,
    "ERR_CPT_CODE_MISMATCH": 422,
    "ERR_NO_RBT_TO_SUPERVISE": 422,
    "ERR_SESSION_OUTSIDE_AUTH_WINDOW": 422,
    "ERR_AUTH_UNITS_EXHAUSTED": 422,
    "ERR_EMPTY_CLAIM": 422,
    "ERR_RENEWAL_CPT_MISMATCH": 422,
    "ERR_APPEAL_LIMIT_REACHED": 422,
    "ERR_PAGINATION_PARAMS": 422,
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
