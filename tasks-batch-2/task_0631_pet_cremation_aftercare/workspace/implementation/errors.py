"""Error catalog and the ApiError exception type.

Every error_id / http_status pair is taken verbatim from PRD section 5
(Error Code Catalogue) and SCAFFOLD.yaml section 1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog: error_id -> http_status -------------------------------
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_CLINIC_REQUIRED_FOR_ACCOUNT_BILLING = ("ERR_CLINIC_REQUIRED_FOR_ACCOUNT_BILLING", 422)
ERR_STALE_CASE_VERSION = ("ERR_STALE_CASE_VERSION", 412)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_SERVICE_TYPE_MISMATCH = ("ERR_SERVICE_TYPE_MISMATCH", 409)
ERR_CUSTODY_CHAIN_BROKEN = ("ERR_CUSTODY_CHAIN_BROKEN", 409)
ERR_RETORT_WINDOW_CONFLICT = ("ERR_RETORT_WINDOW_CONFLICT", 409)
ERR_VIEWING_ROOM_CONFLICT = ("ERR_VIEWING_ROOM_CONFLICT", 409)
ERR_RETORT_OVERLOADED = ("ERR_RETORT_OVERLOADED", 409)
ERR_COOLER_FULL = ("ERR_COOLER_FULL", 409)
ERR_BATCH_EMPTY = ("ERR_BATCH_EMPTY", 409)
ERR_CLINIC_CREDIT_EXCEEDED = ("ERR_CLINIC_CREDIT_EXCEEDED", 409)
ERR_LINE_ITEM_LOCKED = ("ERR_LINE_ITEM_LOCKED", 409)
ERR_PAGINATION_INVALID = ("ERR_PAGINATION_INVALID", 422)
ERR_VIEWING_FIELDS_REQUIRED = ("ERR_VIEWING_FIELDS_REQUIRED", 422)
ERR_SCHEDULE_WINDOW_INVALID = ("ERR_SCHEDULE_WINDOW_INVALID", 422)


def err(spec, message=None):
    """Build an ApiError from a (error_id, http_status) tuple."""
    return ApiError(spec[0], spec[1], message)
