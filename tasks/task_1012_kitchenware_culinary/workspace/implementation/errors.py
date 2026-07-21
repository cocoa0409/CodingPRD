"""Error class and HTTP status catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id -> http status (from the PRD error catalogue).
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_OWNERSHIP": 403,
    "ERR_VALIDATION": 400,
    "ERR_STORE_NOT_FOUND": 404,
    "ERR_SKU_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_CLASS_NOT_FOUND": 404,
    "ERR_REGISTRATION_NOT_FOUND": 404,
    "ERR_SERVICE_TICKET_NOT_FOUND": 404,
    "ERR_RETURN_NOT_FOUND": 404,
    "ERR_SPECIAL_ORDER_NOT_FOUND": 404,
    "ERR_REGISTRY_NOT_FOUND": 404,
    "ERR_LINE_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_ORDER_NOT_FULFILLED": 409,
    "ERR_STORE_CLOSED": 409,
    "ERR_PAYMENT_REQUIRED": 409,
    "ERR_CLASS_NOT_OPEN": 409,
    "ERR_LINE_ALREADY_RETURNED": 409,
    "ERR_DISCONTINUED_SKU": 409,
    "ERR_REGISTRATION_CLOSED": 422,
    "ERR_RETURN_WINDOW_EXPIRED": 422,
    "ERR_CLASS_FULL": 409,
    "ERR_CLASS_STATION_CONFLICT": 409,
    "ERR_SERVICE_SLOT_CONFLICT": 409,
    "ERR_INSUFFICIENT_STOCK": 409,
    "ERR_REFUND_EXCEEDS_PAID": 422,
    "ERR_INSUFFICIENT_POINTS": 422,
}


def err(error_id, message=None):
    """Build an ApiError, looking up the status from the catalog."""
    return ApiError(error_id, ERROR_STATUS.get(error_id, 400), message)
