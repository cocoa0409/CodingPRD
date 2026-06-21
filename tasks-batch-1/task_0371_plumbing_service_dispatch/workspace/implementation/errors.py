"""Error catalog (PRD §5) and the ApiError exception type."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error IDs and their HTTP statuses, exactly as defined in PRD §5 / scaffold §1.6.
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_UNAUTHORIZED = ("ERR_UNAUTHORIZED", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_JOB_VERSION = ("ERR_STALE_JOB_VERSION", 412)
ERR_SKILL_INSUFFICIENT = ("ERR_SKILL_INSUFFICIENT", 409)
ERR_LICENSE_REQUIRED = ("ERR_LICENSE_REQUIRED", 409)
ERR_TECH_DOUBLE_BOOKED = ("ERR_TECH_DOUBLE_BOOKED", 409)
ERR_INSPECTOR_CAPACITY_FULL = ("ERR_INSPECTOR_CAPACITY_FULL", 409)
ERR_EMPTY_ESTIMATE = ("ERR_EMPTY_ESTIMATE", 409)
ERR_INSUFFICIENT_STOCK = ("ERR_INSUFFICIENT_STOCK", 409)
ERR_WARRANTY_EXPIRED = ("ERR_WARRANTY_EXPIRED", 409)
ERR_CREDIT_LIMIT_EXCEEDED = ("ERR_CREDIT_LIMIT_EXCEEDED", 409)
ERR_VALIDATION = ("ERR_VALIDATION", 422)


def err(code_tuple, message=None):
    error_id, http_status = code_tuple
    return ApiError(error_id, http_status, message)
