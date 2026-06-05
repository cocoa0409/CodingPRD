"""Error catalogue (§1.6 / PRD §5). Each error carries its id and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_TIME_WINDOW": 422,
    "ERR_INVALID_SHIFT_STATE": 409,
    "ERR_INVALID_ASSIGNMENT_STATE": 409,
    "ERR_INVALID_BID_STATE": 409,
    "ERR_INVALID_SWAP_STATE": 409,
    "ERR_INVALID_TIME_OFF_STATE": 409,
    "ERR_SHIFT_NOT_ENDED": 409,
    "ERR_SHIFT_NOT_STARTED": 409,
    "ERR_SHIFT_ALREADY_STARTED": 409,
    "ERR_PAY_PERIOD_LOCKED": 409,
    "ERR_OPEN_ASSIGNMENTS_EXIST": 409,
    "ERR_STALE_SHIFT_VERSION": 412,
    "ERR_BID_NOT_WINNER": 409,
    "ERR_CROSS_LOCATION": 409,
    "ERR_WORKER_SUSPENDED": 409,
    "ERR_WORKER_UNAVAILABLE": 409,
    "ERR_MINOR_HOUR_CAP_EXCEEDED": 409,
    "ERR_SHIFT_FULLY_STAFFED": 409,
    "ERR_OVERTIME_GUARDRAIL_EXCEEDED": 409,
    "ERR_TIME_OFF_CONFLICTS_ASSIGNMENT": 409,
}

_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or malformed authentication headers.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted for this operation.",
    "ERR_NOT_FOUND": "A referenced resource does not exist.",
    "ERR_INVALID_REQUEST": "The request body is malformed.",
    "ERR_INVALID_TIME_WINDOW": "end_utc must be strictly after start_utc.",
    "ERR_INVALID_SHIFT_STATE": "The shift is not in a state that permits this transition.",
    "ERR_INVALID_ASSIGNMENT_STATE": "The assignment is not in a state that permits this transition.",
    "ERR_INVALID_BID_STATE": "The bid is not in a state that permits this transition.",
    "ERR_INVALID_SWAP_STATE": "The swap is not in a state that permits this transition.",
    "ERR_INVALID_TIME_OFF_STATE": "The time-off request is not in a state that permits this transition.",
    "ERR_SHIFT_NOT_ENDED": "The shift has not yet ended.",
    "ERR_SHIFT_NOT_STARTED": "The shift has not yet started.",
    "ERR_SHIFT_ALREADY_STARTED": "The shift has already started.",
    "ERR_PAY_PERIOD_LOCKED": "The pay-period is locked.",
    "ERR_OPEN_ASSIGNMENTS_EXIST": "Non-terminal assignments still exist in this pay-period.",
    "ERR_STALE_SHIFT_VERSION": "The shift version is stale.",
    "ERR_BID_NOT_WINNER": "The named bid is not the winning bid.",
    "ERR_CROSS_LOCATION": "The worker does not belong to the shift's location.",
    "ERR_WORKER_SUSPENDED": "The worker is suspended.",
    "ERR_WORKER_UNAVAILABLE": "The worker is unavailable for this shift.",
    "ERR_MINOR_HOUR_CAP_EXCEEDED": "The minor hour cap would be exceeded.",
    "ERR_SHIFT_FULLY_STAFFED": "The shift is already fully staffed.",
    "ERR_OVERTIME_GUARDRAIL_EXCEEDED": "The overtime cost guardrail would be exceeded.",
    "ERR_TIME_OFF_CONFLICTS_ASSIGNMENT": "Time-off conflicts with a scheduled assignment.",
}
