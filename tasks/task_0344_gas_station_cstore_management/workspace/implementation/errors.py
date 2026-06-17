"""Error classes and error-ID constants (§5 catalogue / scaffold errors table)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue: error_id -> http status (verbatim from PRD §5 / scaffold).
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_SHIFT_OWNER = ("ERR_NOT_SHIFT_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_AGE_VERIFICATION_FAILED = ("ERR_AGE_VERIFICATION_FAILED", 422)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_SHIFT_NOT_OPEN = ("ERR_SHIFT_NOT_OPEN", 409)
ERR_PAYMENT_NOT_CAPTURED = ("ERR_PAYMENT_NOT_CAPTURED", 409)
ERR_PUMP_UNAVAILABLE = ("ERR_PUMP_UNAVAILABLE", 409)
ERR_TANK_DOWN = ("ERR_TANK_DOWN", 409)
ERR_TANK_CAPACITY_EXCEEDED = ("ERR_TANK_CAPACITY_EXCEEDED", 409)
ERR_NEGATIVE_VOLUME = ("ERR_NEGATIVE_VOLUME", 409)
ERR_CODE_EXPIRED = ("ERR_CODE_EXPIRED", 409)
ERR_INSUFFICIENT_POINTS = ("ERR_INSUFFICIENT_POINTS", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_DUPLICATE_GRADE = ("ERR_DUPLICATE_GRADE", 409)
ERR_DUPLICATE_PUMP = ("ERR_DUPLICATE_PUMP", 409)
ERR_DUPLICATE_PHONE = ("ERR_DUPLICATE_PHONE", 409)
ERR_VALIDATION = ("ERR_VALIDATION", 422)


def fail(err_tuple, message=None):
    """Raise an ApiError from one of the (error_id, http_status) tuples above."""
    raise ApiError(err_tuple[0], err_tuple[1], message)
