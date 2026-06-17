"""Error catalog and the ApiError exception type."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http status
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_TIME_RANGE": 422,
    "ERR_COVERAGE_MISMATCH": 422,
    "ERR_ONE_WAY_DROPOFF_NOT_ALLOWED": 422,
    "ERR_INVALID_TRANSFER": 422,
    "ERR_ODOMETER_REGRESSION": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_LICENSE_NOT_VERIFIED": 409,
    "ERR_COVERAGE_REQUIRED": 409,
    "ERR_INSUFFICIENT_STOCK": 409,
    "ERR_RESERVATION_LOCKED": 409,
    "ERR_NO_EQUIPMENT_AVAILABLE": 409,
    "ERR_RETURN_LOT_FULL": 409,
    "ERR_EQUIPMENT_DOUBLE_BOOKED": 409,
    "ERR_TRANSFER_IN_PROGRESS": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_VALIDATION_PAGINATION": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
