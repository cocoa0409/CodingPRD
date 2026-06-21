"""Error classes and error-id constants (PRD §5 Error Code Catalogue)."""


class ApiError(Exception):
    """Carries the error_id, human message, and HTTP status for the envelope."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# PRD §5 Error Code Catalogue — (error_id -> http status).
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_NOT_ORDER_OWNER = ("ERR_NOT_ORDER_OWNER", 403)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_ORDER_VERSION = ("ERR_STALE_ORDER_VERSION", 412)
ERR_VALIDATION = ("ERR_VALIDATION", 400)
ERR_FINISHING_NOT_FOR_PRODUCT = ("ERR_FINISHING_NOT_FOR_PRODUCT", 422)
ERR_PRODUCT_INACTIVE = ("ERR_PRODUCT_INACTIVE", 409)
ERR_LINE_NOT_LOCKABLE = ("ERR_LINE_NOT_LOCKABLE", 409)
ERR_FULFILLMENT_REQUIRED = ("ERR_FULFILLMENT_REQUIRED", 409)
ERR_FULFILLMENT_FIELDS_INVALID = ("ERR_FULFILLMENT_FIELDS_INVALID", 422)
ERR_PRESS_DOUBLE_BOOKED = ("ERR_PRESS_DOUBLE_BOOKED", 409)
ERR_BOOKING_INTERVAL_INVALID = ("ERR_BOOKING_INTERVAL_INVALID", 422)
ERR_CAPACITY_EXCEEDED = ("ERR_CAPACITY_EXCEEDED", 409)
ERR_PAYMENT_AMOUNT_MISMATCH = ("ERR_PAYMENT_AMOUNT_MISMATCH", 422)
ERR_PROOF_NOT_REQUIRED = ("ERR_PROOF_NOT_REQUIRED", 409)
ERR_CHANGE_NOTE_REQUIRED = ("ERR_CHANGE_NOTE_REQUIRED", 422)


def err(spec, message=None):
    """Build an ApiError from a (error_id, http_status) tuple constant."""
    error_id, http_status = spec
    return ApiError(error_id, http_status, message)
