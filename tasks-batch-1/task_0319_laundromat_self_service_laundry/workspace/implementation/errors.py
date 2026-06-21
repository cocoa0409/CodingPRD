"""Error catalogue and custom exception class.

Error IDs and HTTP statuses are taken verbatim from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# PRD §5 Error Code Catalogue / SCAFFOLD §1.6
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_NO_ACTIVE_PLAN = ("ERR_NO_ACTIVE_PLAN", 409)
ERR_MACHINE_UNAVAILABLE = ("ERR_MACHINE_UNAVAILABLE", 409)
ERR_DRY_BLOCKS_REQUIRED = ("ERR_DRY_BLOCKS_REQUIRED", 422)
ERR_MEMBER_NOT_ACTIVE = ("ERR_MEMBER_NOT_ACTIVE", 409)
ERR_NO_FREE_CREDIT = ("ERR_NO_FREE_CREDIT", 409)
ERR_INSUFFICIENT_WALLET = ("ERR_INSUFFICIENT_WALLET", 409)
ERR_INSUFFICIENT_POINTS = ("ERR_INSUFFICIENT_POINTS", 409)
ERR_ALREADY_REFUNDED = ("ERR_ALREADY_REFUNDED", 409)
ERR_DISPOSAL_HOLD_ACTIVE = ("ERR_DISPOSAL_HOLD_ACTIVE", 409)
ERR_SHIFT_ALREADY_OPEN = ("ERR_SHIFT_ALREADY_OPEN", 409)
ERR_DUPLICATE_PHONE = ("ERR_DUPLICATE_PHONE", 409)
ERR_VALIDATION = ("ERR_VALIDATION", 422)


def err(spec, message=None):
    """Build an ApiError from a (error_id, http_status) spec tuple."""
    error_id, http_status = spec
    return ApiError(error_id, http_status, message)
