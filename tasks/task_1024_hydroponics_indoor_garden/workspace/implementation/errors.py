"""Error catalog (SCAFFOLD §1.6 / PRD §5) and the ApiError exception."""

# error_id -> http_status
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_OWNERSHIP_REQUIRED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_ACCOUNT_NOT_ACTIVE": 409,
    "ERR_SESSION_NOT_OPEN": 409,
    "ERR_SUBSCRIPTION_INVALID": 409,
    "ERR_HAZMAT_NOT_RETURNABLE": 422,
    "ERR_CONSULTANT_UNAVAILABLE": 409,
    "ERR_ROOM_DOUBLE_BOOKED": 409,
    "ERR_PRODUCT_NOT_IN_ORDER": 409,
    "ERR_INSUFFICIENT_STOCK": 409,
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
    "ERR_STALE_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or error_id
