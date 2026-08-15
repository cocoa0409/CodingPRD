"""Error classes and the error catalog (ids + HTTP statuses)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error catalog: id -> http_status
ERRORS = {
    "ERR_MISSING_OR_INVALID_AUTH_CONTEXT": 400,
    "ERR_INVALID_REQUEST": 400,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_STALE_PERMIT_VERSION": 412,
    "ERR_STALE_CYCLE_VERSION": 412,
    "ERR_PROGRAM_FROZEN": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_PERMIT_NOT_OFFERED": 409,
    "ERR_OFFER_EXPIRED": 409,
    "ERR_LOT_NOT_BOOKABLE": 409,
    "ERR_ROUTE_NOT_ACTIVE": 409,
    "ERR_CYCLE_NOT_OPEN": 409,
    "ERR_EMPLOYEE_NOT_ACTIVE": 409,
    "ERR_TOW_VIOLATION_NOT_ENFORCEABLE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_TOW_HOLD_NOT_ELAPSED": 409,
    "ERR_APPEAL_WINDOW_CLOSED": 409,
    "ERR_NOTICE_EFFECTIVE_TOO_SOON": 422,
    "ERR_DUPLICATE_ACTIVE_PERMIT": 409,
    "ERR_BADGE_NUMBER_TAKEN": 409,
    "ERR_PEAK_WINDOW_OVERLAP": 409,
    "ERR_BILLING_CYCLE_OVERLAP": 409,
    "ERR_CAPACITY_BELOW_OCCUPANCY": 409,
    "ERR_TRIP_SPACING_CONFLICT": 409,
    "ERR_REMOTE_LOT_REQUIRED": 422,
    "ERR_BILLING_HOLD": 402,
    "ERR_NO_OPEN_BILLING_CYCLE": 409,
    "ERR_REINSTATE_BLOCKED": 409,
    "ERR_VIOLATION_PERMIT_MISMATCH": 409,
    "ERR_NOTICE_TARGET_MISMATCH": 422,
}


def raise_error(error_id, message=None):
    status = ERRORS[error_id]
    raise ApiError(error_id, message or error_id, status)
