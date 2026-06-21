"""Error classes and error-id constants (PRD §5 error catalogue)."""


class ApiError(Exception):
    """Carries a machine-readable error_id, HTTP status, and message."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# PRD §5 Error Code Catalogue (exact ids + HTTP status).
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_CUSTOMER_BLOCKED = ("ERR_CUSTOMER_BLOCKED", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_RESTAURANT_CLOSED = ("ERR_RESTAURANT_CLOSED", 409)
ERR_TABLE_DOUBLE_BOOKED = ("ERR_TABLE_DOUBLE_BOOKED", 409)
ERR_AREA_BOUGHT_OUT = ("ERR_AREA_BOUGHT_OUT", 409)
ERR_PACING_EXCEEDED = ("ERR_PACING_EXCEEDED", 409)
ERR_NO_SHOW_TOO_EARLY = ("ERR_NO_SHOW_TOO_EARLY", 409)
ERR_RESCHEDULE_TOO_LATE = ("ERR_RESCHEDULE_TOO_LATE", 409)
ERR_PARTY_SIZE_MISMATCH = ("ERR_PARTY_SIZE_MISMATCH", 422)
ERR_OUTSIDE_SERVICE_PERIOD = ("ERR_OUTSIDE_SERVICE_PERIOD", 422)
ERR_DEPOSIT_REQUIRED = ("ERR_DEPOSIT_REQUIRED", 402)
ERR_AREA_NOT_PRIVATE = ("ERR_AREA_NOT_PRIVATE", 422)
ERR_STALE_TABLE_VERSION = ("ERR_STALE_TABLE_VERSION", 412)
ERR_STALE_AREA_VERSION = ("ERR_STALE_AREA_VERSION", 412)
ERR_NOTIFY_WINDOW_EXPIRED = ("ERR_NOTIFY_WINDOW_EXPIRED", 409)
ERR_NO_MATCHING_TABLE = ("ERR_NO_MATCHING_TABLE", 409)
ERR_VALIDATION = ("ERR_VALIDATION", 422)
ERR_DUPLICATE_PHONE = ("ERR_DUPLICATE_PHONE", 409)
ERR_DUPLICATE_DEPOSIT_HOLD = ("ERR_DUPLICATE_DEPOSIT_HOLD", 409)
ERR_PAGINATION_INVALID = ("ERR_PAGINATION_INVALID", 422)


def err(spec, message=None):
    """Build an ApiError from a (error_id, http_status) tuple constant."""
    error_id, http_status = spec
    return ApiError(error_id, http_status, message)
