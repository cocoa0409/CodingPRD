"""Error classes and error-id constants (SCAFFOLD §1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: id -> http status
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_INVALID_WINDOW = ("ERR_INVALID_WINDOW", 422)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_NO_UNIT_AVAILABLE = ("ERR_NO_UNIT_AVAILABLE", 409)
ERR_CUSTOMER_WINDOW_CONFLICT = ("ERR_CUSTOMER_WINDOW_CONFLICT", 409)
ERR_PARTY_NOT_OPEN = ("ERR_PARTY_NOT_OPEN", 409)
ERR_PARTY_LOCKED = ("ERR_PARTY_LOCKED", 409)
ERR_NOT_COORDINATOR = ("ERR_NOT_COORDINATOR", 403)
ERR_FIT_NOT_CLEARED = ("ERR_FIT_NOT_CLEARED", 409)
ERR_ALTERATION_PENDING = ("ERR_ALTERATION_PENDING", 409)
ERR_BALANCE_OUTSTANDING = ("ERR_BALANCE_OUTSTANDING", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)


def err(spec, message=None):
    """Build an ApiError from an (id, status) tuple constant."""
    error_id, http_status = spec
    return ApiError(error_id, http_status, message)
