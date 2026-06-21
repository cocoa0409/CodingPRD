"""Error classes and error ID constants (from SCAFFOLD §1.6 error catalog)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog (id -> http status) ---
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_UNAUTHORIZED = ("ERR_UNAUTHORIZED", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_STALE_SESSION_VERSION = ("ERR_STALE_SESSION_VERSION", 412)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_NOT_504_IEP_ELIGIBLE = ("ERR_NOT_504_IEP_ELIGIBLE", 422)
ERR_ID_VERIFICATION_FAILED = ("ERR_ID_VERIFICATION_FAILED", 422)
ERR_ACCOMMODATION_NOT_BINDABLE = ("ERR_ACCOMMODATION_NOT_BINDABLE", 409)
ERR_SESSION_WINDOW_OVERLAP = ("ERR_SESSION_WINDOW_OVERLAP", 409)
ERR_CANDIDATE_SCHEDULE_CONFLICT = ("ERR_CANDIDATE_SCHEDULE_CONFLICT", 409)
ERR_SESSION_CLOSED = ("ERR_SESSION_CLOSED", 409)
ERR_SESSION_FULL = ("ERR_SESSION_FULL", 409)
ERR_ACCOMMODATED_FULL = ("ERR_ACCOMMODATED_FULL", 409)
ERR_REFUND_WINDOW_CLOSED = ("ERR_REFUND_WINDOW_CLOSED", 409)
ERR_OFFER_NO_LONGER_VALID = ("ERR_OFFER_NO_LONGER_VALID", 409)


def err(spec, message=None):
    """Build an ApiError from a (error_id, http_status) tuple."""
    error_id, http_status = spec
    return ApiError(error_id, http_status, message)
