"""Error catalogue and the ApiError exception carried through request handling."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status per error id (PRD §5 catalogue).
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_ENUM": 422,
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_AGGREGATOR_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_DEVICE_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_DISPATCH_EVENT_NOT_FOUND": 404,
    "ERR_DISPATCH_NOT_FOUND": 404,
    "ERR_METER_READING_NOT_FOUND": 404,
    "ERR_SETTLEMENT_NOT_FOUND": 404,
    "ERR_PAYMENT_NOT_FOUND": 404,
    "ERR_FORBIDDEN_OWNERSHIP": 403,
    "ERR_INVALID_STATE": 409,
    "ERR_PROGRAM_NOT_ACTIVE": 409,
    "ERR_DEVICE_NOT_ELIGIBLE": 409,
    "ERR_DUPLICATE_ENROLLMENT": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NO_ELIGIBLE_ENROLLMENTS": 409,
    "ERR_NOTIFY_LEAD_NOT_MET": 422,
    "ERR_EVENT_NOT_STARTED": 409,
    "ERR_EVENT_NOT_ENDED": 409,
    "ERR_OVERRIDE_WINDOW_CLOSED": 409,
    "ERR_EVENT_WINDOW_CONFLICT": 409,
    "ERR_SEASON_EVENT_CAP_EXCEEDED": 409,
    "ERR_READING_INTERVAL_OVERLAP": 409,
    "ERR_BASELINE_DATA_MISSING": 422,
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
