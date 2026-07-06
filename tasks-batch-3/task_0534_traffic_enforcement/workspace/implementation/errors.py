class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (id -> http status)
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_PORTAL_AUTH_FAILED = ("ERR_PORTAL_AUTH_FAILED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_SEGREGATION_OF_DUTIES = ("ERR_SEGREGATION_OF_DUTIES", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_DUPLICATE = ("ERR_DUPLICATE", 409)
ERR_PAYMENT_EXISTS = ("ERR_PAYMENT_EXISTS", 409)
ERR_CALIBRATION_LAPSED = ("ERR_CALIBRATION_LAPSED", 422)
ERR_NO_VIOLATION = ("ERR_NO_VIOLATION", 422)
ERR_OWNER_LOOKUP_FAILED = ("ERR_OWNER_LOOKUP_FAILED", 422)
ERR_CONTEST_WINDOW_CLOSED = ("ERR_CONTEST_WINDOW_CLOSED", 422)
ERR_HEARING_TIME_INVALID = ("ERR_HEARING_TIME_INVALID", 422)
ERR_INVALID_REDUCTION = ("ERR_INVALID_REDUCTION", 422)
ERR_NOTHING_OWED = ("ERR_NOTHING_OWED", 422)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)


def err(pair, message=None):
    """Build an ApiError from a (error_id, http_status) constant pair."""
    return ApiError(pair[0], pair[1], message)
