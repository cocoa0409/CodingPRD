"""Error catalogue and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id -> http status (PRD §5 / scaffold §1.6)
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_ITEM_VERSION": 412,
    "ERR_STALE_SETTLEMENT_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_AUTHENTICATION_REQUIRED": 409,
    "ERR_ITEM_NOT_ON_FLOOR": 409,
    "ERR_DUPLICATE_SALE_LINE": 409,
    "ERR_RETURN_WINDOW_NOT_ELAPSED": 409,
    "ERR_RETURN_WINDOW_ELAPSED": 409,
    "ERR_PRICE_BELOW_FLOOR": 422,
    "ERR_SETTLEMENT_DATE_TAKEN": 409,
    "ERR_INSUFFICIENT_STORE_CREDIT": 422,
    "ERR_INVALID_SCHEDULE": 422,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_EMAIL": 409,
    "ERR_AGREEMENT_PRECONDITION": 409,
    "ERR_BATCH_CLOSED": 409,
    "ERR_AGREEMENT_TERMINATED": 409,
    "ERR_LIST_PRICE_REQUIRED": 422,
    "ERR_VALIDATION_PAGINATION": 400,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
