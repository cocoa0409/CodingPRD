class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (id -> http status)
ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_CUSTOMER_BANNED": 409,
    "ERR_SERIES_DISCONTINUED": 409,
    "ERR_PAST_CUTOFF": 422,
    "ERR_ISSUE_NOT_ON_SALE": 409,
    "ERR_ISSUE_ALREADY_ON_SALE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_ALLOCATION_ALREADY_RUN": 409,
    "ERR_INSUFFICIENT_COPIES": 409,
    "ERR_INSUFFICIENT_STORE_CREDIT": 402,
    "ERR_EVENT_FULL": 409,
    "ERR_EVENT_CLOSED": 409,
    "ERR_EVENT_TIME_CONFLICT": 409,
    "ERR_REGISTRATION_TIME_CONFLICT": 409,
    "ERR_EVENT_ALREADY_STARTED": 422,
    "ERR_DUPLICATE_REGISTRATION": 409,
    "ERR_SALE_PRICE_REQUIRED": 422,
    "ERR_DISPUTE_LIMIT_REACHED": 409,
    "ERR_NEGATIVE_INVENTORY": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERR[error_id], message)
