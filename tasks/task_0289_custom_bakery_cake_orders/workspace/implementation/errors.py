"""Error catalog and the ApiError exception."""


class ApiError(Exception):
    """Carries error_id, http_status and a human message."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error IDs (from §1.6 / PRD §5). HTTP codes paired here for convenience.
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_ORDER_OWNER = ("ERR_NOT_ORDER_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_REFERENCE_NOT_FOUND = ("ERR_REFERENCE_NOT_FOUND", 404)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_ORDER_VERSION = ("ERR_STALE_ORDER_VERSION", 412)
ERR_DIETARY_CONFLICT = ("ERR_DIETARY_CONFLICT", 422)
ERR_OPTION_NOT_ALLOWED = ("ERR_OPTION_NOT_ALLOWED", 422)
ERR_LEAD_TIME_NOT_MET = ("ERR_LEAD_TIME_NOT_MET", 422)
ERR_PAST_ORDER_CUTOFF = ("ERR_PAST_ORDER_CUTOFF", 422)
ERR_ROUTE_WINDOW_CONFLICT = ("ERR_ROUTE_WINDOW_CONFLICT", 409)
ERR_PROOF_NOT_APPROVED = ("ERR_PROOF_NOT_APPROVED", 409)
ERR_PRODUCTION_DAY_FULL = ("ERR_PRODUCTION_DAY_FULL", 409)
ERR_INSUFFICIENT_CREDIT = ("ERR_INSUFFICIENT_CREDIT", 422)
ERR_PAYMENT_AMOUNT_MISMATCH = ("ERR_PAYMENT_AMOUNT_MISMATCH", 422)
ERR_LINE_IMMUTABLE = ("ERR_LINE_IMMUTABLE", 409)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_VALIDATION_PAGINATION = ("ERR_VALIDATION_PAGINATION", 400)


def err(pair, message=None):
    """Build an ApiError from one of the (error_id, http_status) pairs above."""
    return ApiError(pair[0], pair[1], message)
