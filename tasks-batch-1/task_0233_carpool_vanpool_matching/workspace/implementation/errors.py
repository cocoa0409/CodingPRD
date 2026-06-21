"""Error catalogue (PRD §5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error-id -> HTTP status (PRD §5 catalogue)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_STALE_TRIP_VERSION": 412,
    "ERR_STALE_POOL_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_DEPENDENCY_NOT_READY": 409,
    "ERR_RELIABILITY_TOO_LOW": 409,
    "ERR_TRIP_WINDOW_OVERLAP": 409,
    "ERR_RIDER_DOUBLE_BOOKED": 409,
    "ERR_SEATS_EXHAUSTED": 409,
    "ERR_POOL_CAPACITY_EXCEEDED": 409,
    "ERR_GRH_EVENT_CAP": 409,
    "ERR_GRH_ANNUAL_CAP": 409,
    "ERR_INSUFFICIENT_WALLET": 402,
    "ERR_NO_MATCH_FOUND": 422,
    "ERR_VALIDATION_DRIVER_REQUIRED": 422,
    "ERR_PROGRAM_BUDGET_EXHAUSTED": 409,
    "ERR_MEMBERSHIP_DUPLICATE": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
