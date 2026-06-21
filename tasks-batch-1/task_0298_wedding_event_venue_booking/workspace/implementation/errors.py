"""Error catalog and the ApiError exception carrying error_id + HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (id -> http). Mirrors PRD §5 / scaffold §1.6 exactly.
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_TIME_WINDOW": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_BOOKING_VERSION": 412,
    "ERR_CAPACITY_EXCEEDED": 422,
    "ERR_SPACE_KIND_MISMATCH": 422,
    "ERR_SPACE_DOUBLE_BOOKED": 409,
    "ERR_WALKTHROUGH_CONFLICT": 409,
    "ERR_COORDINATOR_AT_CAPACITY": 409,
    "ERR_VENDOR_COI_MISSING": 409,
    "ERR_GUARANTEE_DEADLINE_PASSED": 409,
    "ERR_DEPOSIT_NOT_SETTLED": 402,
    "ERR_BALANCE_OUTSTANDING": 402,
    "ERR_OVERPAYMENT": 422,
    "ERR_RESCHEDULE_IN_PROGRESS": 409,
    "ERR_WALKTHROUGH_AFTER_EVENT": 422,
    "ERR_COI_EXPIRES_BEFORE_EVENT": 422,
    "ERR_VALIDATION_LIMIT": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
