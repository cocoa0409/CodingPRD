"""Error catalog and the ApiError exception type."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error ID -> HTTP status (from PRD section 5 / scaffold 1.6)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_SITE_CONTACT": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_ACCOUNT_NOT_ACTIVE": 409,
    "ERR_SITE_ARCHIVED": 409,
    "ERR_CONTRACT_NOT_ACTIVE": 409,
    "ERR_CREW_INACTIVE": 409,
    "ERR_FLOOR_INELIGIBLE": 409,
    "ERR_NO_TIME_ENTRY": 409,
    "ERR_OPEN_TIME_ENTRY": 409,
    "ERR_INVALID_CLOCK_RANGE": 422,
    "ERR_SHIFT_CAPACITY_EXCEEDED": 409,
    "ERR_CREW_DOUBLE_BOOKED": 409,
    "ERR_SCHEDULE_WINDOW_CONFLICT": 409,
    "ERR_CALLBACK_NOT_COMPLETE": 409,
    "ERR_REOPEN_NOT_ALLOWED": 409,
    "ERR_DUPLICATE_PERIOD": 409,
    "ERR_PERIOD_OPEN": 409,
    "ERR_VISIT_IN_PROGRESS": 409,
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS.get(error_id, 400), message)
