"""Error catalog (PRD §5 / SCAFFOLD §1.6) and the ApiError exception."""


class ApiError(Exception):
    """An error carrying an error_id, human message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http_status (PRD §5 / SCAFFOLD §1.6)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_NO_WAGE_RULESET": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_TIMESHEET_FROZEN": 409,
    "ERR_OPEN_PUNCH_IN_WEEK": 409,
    "ERR_EXEMPT_NOT_ELIGIBLE": 422,
    "ERR_EDIT_REASON_REQUIRED": 422,
    "ERR_NEGATIVE_DURATION": 422,
    "ERR_PUNCH_OVERLAP": 409,
    "ERR_PUNCH_ALREADY_OPEN": 409,
    "ERR_INVALID_SCHEDULE": 422,
    "ERR_SHIFT_OVERLAP": 409,
    "ERR_EMPTY_TIP_POOL": 409,
    "ERR_EMPTY_PAYROLL_RUN": 409,
    "ERR_WEEK_OUTSIDE_PERIOD": 422,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_REQUEST": 422,
    "ERR_DUPLICATE_RULESET": 409,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    """Construct an ApiError using the catalog's HTTP status."""
    return ApiError(error_id, ERROR_STATUS[error_id], message)
