"""Error catalogue (PRD §5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error-id -> HTTP status, straight from PRD §5.
ERROR_STATUS = {
    "ERR_MISSING_AUTH": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_ROUTE_NOT_OPEN": 409,
    "ERR_ROUTE_EMPTY": 409,
    "ERR_STOPS_OPEN": 409,
    "ERR_AREA_NOT_COVERED": 409,
    "ERR_EUTHANASIA_NOT_PERMITTED": 403,
    "ERR_EUTHANASIA_NOT_REFERABLE": 409,
    "ERR_VET_REQUIRED": 403,
    "ERR_DEA_INVALID": 403,
    "ERR_WITNESS_CONFLICT": 403,
    "ERR_DOSE_BELOW_MINIMUM": 422,
    "ERR_EUTHANASIA_LOG_INCOMPLETE": 409,
    "ERR_NO_APPROVED_ESTIMATE": 409,
    "ERR_APPT_NOT_IN_VISIT_PHASE": 409,
    "ERR_STOP_WINDOW_CONFLICT": 409,
    "ERR_VEHICLE_DOUBLE_BOOKED": 409,
    "ERR_VEHICLE_UNAVAILABLE": 409,
    "ERR_INSUFFICIENT_STOCK": 409,
    "ERR_CONTROLLED_COUNT_MISMATCH": 409,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
    "ERR_STALE_ROUTE_DAY_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
