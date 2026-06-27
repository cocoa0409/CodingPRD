"""Error classes and error ID constants from the scaffold's error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (error_id -> http status)
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_UNAUTHORIZED = ("ERR_UNAUTHORIZED", 403)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_REFERENCED_NOT_FOUND = ("ERR_REFERENCED_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_CLIENT_RISK_BLOCKED = ("ERR_CLIENT_RISK_BLOCKED", 409)
ERR_INTAKE_NOT_CLEARED = ("ERR_INTAKE_NOT_CLEARED", 409)
ERR_LICENSE_STATE_MISMATCH = ("ERR_LICENSE_STATE_MISMATCH", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_SESSION_OVERLAP = ("ERR_SESSION_OVERLAP", 409)
ERR_THERAPIST_DOUBLE_BOOKED = ("ERR_THERAPIST_DOUBLE_BOOKED", 409)
ERR_NO_CREDIT = ("ERR_NO_CREDIT", 409)
ERR_THREAD_NOT_OPEN = ("ERR_THREAD_NOT_OPEN", 409)
ERR_DUPLICATE_SUBSCRIPTION = ("ERR_DUPLICATE_SUBSCRIPTION", 409)
ERR_CYCLE_NOT_DUE = ("ERR_CYCLE_NOT_DUE", 409)
ERR_NO_ELIGIBLE_THERAPIST = ("ERR_NO_ELIGIBLE_THERAPIST", 409)
ERR_CANCEL_NOT_DUE = ("ERR_CANCEL_NOT_DUE", 409)
ERR_VALIDATION = ("ERR_VALIDATION", 422)


def err(catalog_entry, message=None):
    error_id, http_status = catalog_entry
    return ApiError(error_id, http_status, message)
