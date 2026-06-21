"""Error catalog and the ApiError exception type.

Every error_id / http_status pair is taken verbatim from PRD §5 and
SCAFFOLD §1.6. Do not invent codes.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog (PRD §5 / SCAFFOLD §1.6) ---------------------------------
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_FK_NOT_FOUND = ("ERR_FK_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_SCREENING_FAILED = ("ERR_SCREENING_FAILED", 409)
ERR_APPLICANT_NOT_APPROVED = ("ERR_APPLICANT_NOT_APPROVED", 409)
ERR_UNIT_NOT_AVAILABLE = ("ERR_UNIT_NOT_AVAILABLE", 409)
ERR_DEPOSIT_REQUIRED = ("ERR_DEPOSIT_REQUIRED", 409)
ERR_LEASE_NOT_ENDED = ("ERR_LEASE_NOT_ENDED", 409)
ERR_LEASE_OVERLAP = ("ERR_LEASE_OVERLAP", 409)
ERR_EVICTION_WINDOW_OVERLAP = ("ERR_EVICTION_WINDOW_OVERLAP", 409)
ERR_LEASE_STILL_ACTIVE = ("ERR_LEASE_STILL_ACTIVE", 409)
ERR_CANNOT_WAIVE_RENT = ("ERR_CANNOT_WAIVE_RENT", 409)
ERR_CURE_WINDOW_CLOSED = ("ERR_CURE_WINDOW_CLOSED", 409)
ERR_CURE_WINDOW_OPEN = ("ERR_CURE_WINDOW_OPEN", 409)
ERR_ARREARS_NOT_CLEARED = ("ERR_ARREARS_NOT_CLEARED", 409)
ERR_OPEN_WORK_ORDERS = ("ERR_OPEN_WORK_ORDERS", 409)
ERR_ACTUAL_COST_REQUIRED = ("ERR_ACTUAL_COST_REQUIRED", 422)
ERR_TRUST_INSUFFICIENT = ("ERR_TRUST_INSUFFICIENT", 409)
ERR_NOTHING_TO_DISTRIBUTE = ("ERR_NOTHING_TO_DISTRIBUTE", 409)


def err(catalog_entry, message=None):
    error_id, http_status = catalog_entry
    return ApiError(error_id, http_status, message)
