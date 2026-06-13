"""Error classes and error-id constants for the Traffic Citation API.

Error catalog (id -> http status) per PRD §5 / scaffold Table 6.
"""


class ApiError(Exception):
    """An error carrying a machine-readable error_id and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog (id -> http status) ---
ERR_MISSING_AUTH = ("ERR_MISSING_AUTH", 401)
ERR_FORBIDDEN_FOR_ROLE = ("ERR_FORBIDDEN_FOR_ROLE", 403)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_NO_CHARGES = ("ERR_NO_CHARGES", 409)
ERR_OVERPAYMENT = ("ERR_OVERPAYMENT", 409)
ERR_HAS_PAYMENTS = ("ERR_HAS_PAYMENTS", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_NOT_YET_LATE = ("ERR_NOT_YET_LATE", 409)
ERR_PENALTY_ALREADY_APPLIED = ("ERR_PENALTY_ALREADY_APPLIED", 409)
ERR_INVALID_HEARING_DATE = ("ERR_INVALID_HEARING_DATE", 409)
ERR_CONTINUANCE_LIMIT = ("ERR_CONTINUANCE_LIMIT", 409)
ERR_ALREADY_CONTESTED = ("ERR_ALREADY_CONTESTED", 409)
ERR_SCHOOL_INELIGIBLE = ("ERR_SCHOOL_INELIGIBLE", 409)
ERR_FINE_UNPAID = ("ERR_FINE_UNPAID", 409)
ERR_SCHOOL_DEADLINE_PASSED = ("ERR_SCHOOL_DEADLINE_PASSED", 409)
ERR_INSTALLMENT_TOO_SMALL = ("ERR_INSTALLMENT_TOO_SMALL", 409)
ERR_HOLD_CONDITION_UNMET = ("ERR_HOLD_CONDITION_UNMET", 409)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)


def err(pair, message=None):
    """Build an ApiError from one of the (error_id, http_status) tuples above."""
    error_id, http_status = pair
    return ApiError(error_id, http_status, message)
