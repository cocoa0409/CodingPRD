"""Error catalogue and the ApiError exception type.

Every error_id / http_status pair traces to PRD §5 (Error Code Catalogue)
and SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue: error_id -> http_status (PRD §5)
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_PACKAGE_RETIRED = ("ERR_PACKAGE_RETIRED", 409)
ERR_LEAD_TIME_VIOLATED = ("ERR_LEAD_TIME_VIOLATED", 409)
ERR_LEG_WINDOW_CONFLICT = ("ERR_LEG_WINDOW_CONFLICT", 409)
ERR_VENUE_OVERBOOKED = ("ERR_VENUE_OVERBOOKED", 409)
ERR_LEG_OUT_OF_ORDER = ("ERR_LEG_OUT_OF_ORDER", 409)
ERR_BELOW_MIN_HEADCOUNT = ("ERR_BELOW_MIN_HEADCOUNT", 422)
ERR_DIETARY_EXCEEDS_HEADCOUNT = ("ERR_DIETARY_EXCEEDS_HEADCOUNT", 422)
ERR_OPEN_CHANGE_REQUEST = ("ERR_OPEN_CHANGE_REQUEST", 409)
ERR_STALE_ORDER_VERSION = ("ERR_STALE_ORDER_VERSION", 412)
ERR_BALANCE_UNPAID = ("ERR_BALANCE_UNPAID", 409)
ERR_STAFF_POOL_EXHAUSTED = ("ERR_STAFF_POOL_EXHAUSTED", 409)
ERR_DUPLICATE_EMAIL = ("ERR_DUPLICATE_EMAIL", 409)
ERR_INVALID_PAYMENT = ("ERR_INVALID_PAYMENT", 422)
ERR_VALIDATION_WINDOW = ("ERR_VALIDATION_WINDOW", 422)


def err(pair, message=""):
    """Build an ApiError from an (error_id, http_status) tuple."""
    return ApiError(pair[0], pair[1], message)
