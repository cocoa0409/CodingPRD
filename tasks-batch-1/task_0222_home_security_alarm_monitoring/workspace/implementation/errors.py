"""Error classes and error-id constants (from scaffold §1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http status
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_ACCOUNT_OWNER = ("ERR_NOT_ACCOUNT_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_REFERENCE_NOT_FOUND = ("ERR_REFERENCE_NOT_FOUND", 422)
ERR_VALIDATION = ("ERR_VALIDATION", 422)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_TEST_MODE_ACTIVE = ("ERR_TEST_MODE_ACTIVE", 409)
ERR_COMMUNICATOR_OFFLINE = ("ERR_COMMUNICATOR_OFFLINE", 409)
ERR_CELLULAR_NOT_ENTITLED = ("ERR_CELLULAR_NOT_ENTITLED", 422)
ERR_SENSOR_LIMIT_EXCEEDED = ("ERR_SENSOR_LIMIT_EXCEEDED", 409)
ERR_DUPLICATE_ZONE = ("ERR_DUPLICATE_ZONE", 409)
ERR_PERMIT_ALREADY_ACTIVE = ("ERR_PERMIT_ALREADY_ACTIVE", 409)
ERR_DUPLICATE_PERMIT_NUMBER = ("ERR_DUPLICATE_PERMIT_NUMBER", 409)
ERR_OPEN_DISPATCH = ("ERR_OPEN_DISPATCH", 409)
ERR_TEST_MODE_ALREADY_OPEN = ("ERR_TEST_MODE_ALREADY_OPEN", 409)
ERR_SIGNAL_DEBOUNCED = ("ERR_SIGNAL_DEBOUNCED", 409)


def err(pair, message=None):
    """Build an ApiError from a (error_id, http) tuple."""
    return ApiError(pair[0], pair[1], message)
