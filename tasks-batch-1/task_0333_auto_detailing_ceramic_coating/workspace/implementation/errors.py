"""Error catalogue (PRD §5) and the ApiError exception type."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error ID -> HTTP status (PRD §5 error catalogue)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_RESOURCE_MODE_MISMATCH": 422,
    "ERR_BAY_NO_CERAMIC": 422,
    "ERR_STALE_BAY_VERSION": 412,
    "ERR_RESOURCE_UNAVAILABLE": 409,
    "ERR_BAY_TIME_CONFLICT": 409,
    "ERR_MOBILE_BUFFER_CONFLICT": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_PHOTO_REQUIRED": 409,
    "ERR_CURE_NOT_ELAPSED": 409,
    "ERR_NO_CREDIT_AVAILABLE": 409,
    "ERR_STALE_CLAIM_VERSION": 412,
    "ERR_GUARANTEE_EXPIRED": 409,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
    "ERR_BALANCE_OUTSTANDING": 409,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
