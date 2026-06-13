"""Error catalog (SCAFFOLD §1.6 / PRD §5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id -> http status
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_CARTS_INCOMPLETE": 409,
    "ERR_PLAN_ARCHIVED": 409,
    "ERR_ADDRESS_IN_USE": 409,
    "ERR_DATE_DOUBLE_BOOKED": 409,
    "ERR_REPORT_TOO_EARLY": 409,
    "ERR_CONTAMINATION_NOT_RECYCLING": 409,
    "ERR_NO_PAYMENT_METHOD": 409,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)
