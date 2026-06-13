"""Error catalog and the ApiError exception.

Error IDs and HTTP statuses are taken verbatim from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Auth / gatekeeping ---
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)

# --- Business ---
ERR_LOT_NOT_AVAILABLE = ("ERR_LOT_NOT_AVAILABLE", 409)
ERR_LOCKER_QUARANTINED = ("ERR_LOCKER_QUARANTINED", 409)
ERR_AGING_NOT_COMPLETE = ("ERR_AGING_NOT_COMPLETE", 409)
ERR_WINDOW_CUTOFF_PASSED = ("ERR_WINDOW_CUTOFF_PASSED", 422)
ERR_CUT_TYPE_MISMATCH = ("ERR_CUT_TYPE_MISMATCH", 422)
ERR_OUTPUT_NOT_GRIND = ("ERR_OUTPUT_NOT_GRIND", 422)
ERR_SHARE_OVERCOMMITTED = ("ERR_SHARE_OVERCOMMITTED", 409)
ERR_LOCKER_OVER_CAPACITY = ("ERR_LOCKER_OVER_CAPACITY", 409)
ERR_INSUFFICIENT_LOT_WEIGHT = ("ERR_INSUFFICIENT_LOT_WEIGHT", 409)
ERR_HOLIDAY_CAPACITY_EXCEEDED = ("ERR_HOLIDAY_CAPACITY_EXCEEDED", 409)
ERR_STALE_LOT_VERSION = ("ERR_STALE_LOT_VERSION", 412)
ERR_STALE_LOCKER_VERSION = ("ERR_STALE_LOCKER_VERSION", 412)


def fail(spec, message=None):
    """Raise an ApiError from an (error_id, http_status) tuple."""
    error_id, http_status = spec
    raise ApiError(error_id, http_status, message)
