class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (id -> http status)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_NOT_BOOKING_OWNER = "ERR_NOT_BOOKING_OWNER"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_VALIDATION = "ERR_VALIDATION"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_TEE_TIME_CLOSED = "ERR_TEE_TIME_CLOSED"
ERR_DUPLICATE_BOOKING = "ERR_DUPLICATE_BOOKING"
ERR_GOLFER_TIME_CONFLICT = "ERR_GOLFER_TIME_CONFLICT"
ERR_SLOT_START_PASSED = "ERR_SLOT_START_PASSED"
ERR_SLOT_FULL_NO_STANDBY = "ERR_SLOT_FULL_NO_STANDBY"
ERR_STALE_TEE_TIME_VERSION = "ERR_STALE_TEE_TIME_VERSION"
ERR_REVISION_NOT_MONOTONIC = "ERR_REVISION_NOT_MONOTONIC"
ERR_TEE_INTERVAL_CONFLICT = "ERR_TEE_INTERVAL_CONFLICT"


def unauthenticated(msg="Missing or invalid authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role not permitted for this operation."):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_booking_owner(msg="Caller does not own this booking."):
    return ApiError(ERR_NOT_BOOKING_OWNER, 403, msg)


def not_found(msg="Referenced resource does not exist."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def validation(msg="Validation failed."):
    return ApiError(ERR_VALIDATION, 422, msg)


def invalid_state(msg="Operation not allowed from current state."):
    return ApiError(ERR_INVALID_STATE, 409, msg)
