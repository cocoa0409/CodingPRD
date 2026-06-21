"""Custom exception class and error-id constants.

Every error_id and HTTP status is taken verbatim from the PRD §5 error
catalogue and SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalogue (id -> http status) -----------------------------------
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_VALIDATION = ("ERR_VALIDATION", 400)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_TIER_INSUFFICIENT = ("ERR_TIER_INSUFFICIENT", 422)
ERR_CAREGIVER_SUSPENDED = ("ERR_CAREGIVER_SUSPENDED", 422)
ERR_POSTING_MISMATCH = ("ERR_POSTING_MISMATCH", 422)
ERR_RATE_BELOW_FLOOR = ("ERR_RATE_BELOW_FLOOR", 422)
ERR_RECURRENCE_INVALID = ("ERR_RECURRENCE_INVALID", 422)
ERR_CAREGIVER_DOUBLE_BOOKED = ("ERR_CAREGIVER_DOUBLE_BOOKED", 409)
ERR_FAMILY_WINDOW_CONFLICT = ("ERR_FAMILY_WINDOW_CONFLICT", 409)
ERR_INVALID_INTERVAL = ("ERR_INVALID_INTERVAL", 422)
ERR_BOOKING_NOT_COMPLETED = ("ERR_BOOKING_NOT_COMPLETED", 422)
ERR_INSUFFICIENT_ESCROW = ("ERR_INSUFFICIENT_ESCROW", 422)
ERR_PAYOUT_SESSION_INVALID = ("ERR_PAYOUT_SESSION_INVALID", 422)
ERR_NO_ELIGIBLE_CAREGIVER = ("ERR_NO_ELIGIBLE_CAREGIVER", 422)


def err(spec, message=None):
    """Build an ApiError from a (error_id, http_status) tuple constant."""
    return ApiError(spec[0], spec[1], message)
