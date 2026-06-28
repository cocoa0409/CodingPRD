"""Error classes and error-id constants.

Every error id and HTTP status traces to PRD §5 (Error Code Catalogue) and the
scaffold §1.6 error catalog.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# PRD §5 / scaffold §1.6
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_OWNERSHIP_VIOLATION = ("ERR_OWNERSHIP_VIOLATION", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_VALIDATION = ("ERR_VALIDATION", 400)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_SESSION_VERSION = ("ERR_STALE_SESSION_VERSION", 412)
ERR_STALE_PACK_VERSION = ("ERR_STALE_PACK_VERSION", 412)
ERR_MEMBER_SUSPENDED = ("ERR_MEMBER_SUSPENDED", 403)
ERR_SCHEDULE_CONFLICT = ("ERR_SCHEDULE_CONFLICT", 409)
ERR_BIKE_UNAVAILABLE = ("ERR_BIKE_UNAVAILABLE", 409)
ERR_DUPLICATE_RESERVATION = ("ERR_DUPLICATE_RESERVATION", 409)
ERR_NO_CHARGEABLE_PACK = ("ERR_NO_CHARGEABLE_PACK", 402)
ERR_SESSION_FULL = ("ERR_SESSION_FULL", 409)
ERR_WAITLIST_FULL = ("ERR_WAITLIST_FULL", 409)
ERR_INSUFFICIENT_STOCK = ("ERR_INSUFFICIENT_STOCK", 409)
ERR_WINDOW_CLOSED = ("ERR_WINDOW_CLOSED", 409)
ERR_PRODUCT_DISCONTINUED = ("ERR_PRODUCT_DISCONTINUED", 409)
ERR_SESSION_NOT_FULL = ("ERR_SESSION_NOT_FULL", 409)
ERR_PARENT_RESERVATION_NOT_ATTENDED = ("ERR_PARENT_RESERVATION_NOT_ATTENDED", 409)


def err(pair, message=None):
    """Build an ApiError from one of the (id, http) tuples above."""
    error_id, http_status = pair
    return ApiError(error_id, http_status, message)
