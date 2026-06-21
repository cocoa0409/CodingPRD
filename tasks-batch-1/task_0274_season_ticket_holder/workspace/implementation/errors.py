"""Error catalog and the ApiError exception used across the application."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> default HTTP status.
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCED_RESOURCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_SECTION_MISMATCH": 422,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEAT_WINDOW_CONFLICT": 409,
    "ERR_PARKING_ZONE_FULL": 409,
    "ERR_TRANSFER_NOT_ELIGIBLE": 409,
    "ERR_PAYMENT_PLAN_EXISTS": 409,
    "ERR_STALE_SUBSCRIPTION_VERSION": 412,
    "ERR_VALIDATION_FROM_TERMINAL": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
