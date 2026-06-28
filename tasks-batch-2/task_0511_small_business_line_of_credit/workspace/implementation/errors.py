"""Error catalog. Error IDs and HTTP statuses come from SCAFFOLD §1.6 / PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- catalog ---
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_SEGREGATION_OF_DUTIES = ("ERR_SEGREGATION_OF_DUTIES", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_MERCHANT_BLOCKLISTED = ("ERR_MERCHANT_BLOCKLISTED", 409)
ERR_FEED_STALE = ("ERR_FEED_STALE", 409)
ERR_EXCESS_NSF = ("ERR_EXCESS_NSF", 409)
ERR_SCORE_BELOW_FLOOR = ("ERR_SCORE_BELOW_FLOOR", 409)
ERR_APPLICATION_NOT_APPROVED = ("ERR_APPLICATION_NOT_APPROVED", 409)
ERR_REMITTANCE_NOT_DUE = ("ERR_REMITTANCE_NOT_DUE", 409)
ERR_REMITTANCE_OVERLAP = ("ERR_REMITTANCE_OVERLAP", 409)
ERR_STATEMENT_OVERLAP = ("ERR_STATEMENT_OVERLAP", 409)
ERR_LIMIT_EXCEEDED = ("ERR_LIMIT_EXCEEDED", 409)
ERR_LINE_NOT_DRAWABLE = ("ERR_LINE_NOT_DRAWABLE", 409)
ERR_VALIDATION = ("ERR_VALIDATION", 422)


def err(spec, message=None):
    """Build an ApiError from a (error_id, http_status) tuple."""
    return ApiError(spec[0], spec[1], message)
