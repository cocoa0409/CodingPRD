"""Error catalog and the ApiError exception type.

Every error_id and HTTP status here is taken verbatim from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (PRD §5 / SCAFFOLD §1.6)
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_STALE_SITE_VERSION = ("ERR_STALE_SITE_VERSION", 412)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_RATE_PLAN_TYPE_MISMATCH = ("ERR_RATE_PLAN_TYPE_MISMATCH", 422)
ERR_MAX_STAY_EXCEEDED = ("ERR_MAX_STAY_EXCEEDED", 422)
ERR_SITE_UNAVAILABLE = ("ERR_SITE_UNAVAILABLE", 409)
ERR_MAINTENANCE_CONFLICT = ("ERR_MAINTENANCE_CONFLICT", 409)
ERR_DATE_OVERLAP = ("ERR_DATE_OVERLAP", 409)
ERR_SEASON_OVERLAP = ("ERR_SEASON_OVERLAP", 409)
ERR_PAYMENT_AMOUNT_INVALID = ("ERR_PAYMENT_AMOUNT_INVALID", 422)
ERR_PAYMENT_ALREADY_SETTLED = ("ERR_PAYMENT_ALREADY_SETTLED", 409)
ERR_ADDON_LOCKED = ("ERR_ADDON_LOCKED", 409)
ERR_VALIDATION_FAILED = ("ERR_VALIDATION_FAILED", 422)
ERR_CLOCK_INVALID = ("ERR_CLOCK_INVALID", 422)


def err(spec, message=None):
    """Build an ApiError from a (error_id, http_status) tuple."""
    return ApiError(spec[0], spec[1], message)
