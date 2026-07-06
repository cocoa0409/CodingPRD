"""Error classes and error ID constants."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (id -> http status)
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_DEPENDENCY_NOT_READY = ("ERR_DEPENDENCY_NOT_READY", 409)
ERR_INVALID_GRADE_FOR_NEW = ("ERR_INVALID_GRADE_FOR_NEW", 422)
ERR_INSPECTION_INCOMPLETE = ("ERR_INSPECTION_INCOMPLETE", 422)
ERR_PREORDER_WINDOW_CLOSED = ("ERR_PREORDER_WINDOW_CLOSED", 409)
ERR_PICKUP_CAPACITY_EXCEEDED = ("ERR_PICKUP_CAPACITY_EXCEEDED", 409)
ERR_ALLOCATION_EXHAUSTED = ("ERR_ALLOCATION_EXHAUSTED", 409)
ERR_SLOT_OVERLAP = ("ERR_SLOT_OVERLAP", 409)
ERR_INSUFFICIENT_CREDIT = ("ERR_INSUFFICIENT_CREDIT", 402)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_SLOT_INACTIVE = ("ERR_SLOT_INACTIVE", 409)


def err(pair, message=None):
    """Build an ApiError from a (error_id, http_status) tuple."""
    return ApiError(pair[0], pair[1], message)
