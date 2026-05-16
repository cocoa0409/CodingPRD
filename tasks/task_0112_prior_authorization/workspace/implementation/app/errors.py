"""Error catalog (SCAFFOLD §1.6 / PRD §5) and Flask handlers."""
from flask import Flask, jsonify

from .responses import error_response


# Map of error_id -> HTTP status code.
ERROR_CATALOG = {
    "ERR_AUTH_MISSING": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_PRIOR_REQUEST_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_MISMATCH": 409,
    "ERR_CATALOG_RETIRED": 409,
    "ERR_PATIENT_INACTIVE": 409,
    "ERR_PROVIDER_SUSPENDED": 409,
    "ERR_RESUBMISSION_ALREADY_EXISTS": 409,
    "ERR_APPEAL_ALREADY_FILED": 409,
    "ERR_PEER_REVIEW_ALREADY_SCHEDULED": 409,
    "ERR_PEER_REVIEW_TIME_CONFLICT": 409,
    "ERR_EVIDENCE_DUPLICATE_URI": 409,
    "ERR_EXPEDITED_JUSTIFICATION_REQUIRED": 422,
    "ERR_EVIDENCE_INSUFFICIENT": 422,
    "ERR_EVIDENCE_REUSE_MISMATCH": 422,
    "ERR_PRIOR_REQUEST_NOT_EXPIRED": 422,
    "ERR_INVALID_APPROVED_UNITS": 422,
    "ERR_DENIAL_REASON_REQUIRED": 422,
    "ERR_APPEAL_TIER_ROLE_MISMATCH": 403,
    "ERR_APPEAL_TIER_OUT_OF_ORDER": 422,
    "ERR_APPEAL_DEADLINE_EXPIRED": 422,
    "ERR_EVIDENCE_SIZE_INVALID": 422,
    "ERR_INVALID_P2P_OUTCOME": 422,
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
