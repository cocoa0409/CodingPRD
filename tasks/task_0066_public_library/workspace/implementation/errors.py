"""Error classes and HTTP status catalog."""


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERROR_CATALOG = {
    "ERR_AUTH_REQUIRED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_INPUT": 422,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_COPY_NOT_AVAILABLE": 409,
    "ERR_CARD_NOT_ACTIVE": 409,
    "ERR_IDENTITY_NOT_VERIFIED": 409,
    "ERR_READER_BLACKLISTED": 409,
    "ERR_UNPAID_FINE": 409,
    "ERR_QUOTA_EXCEEDED": 409,
    "ERR_RENEWAL_LIMIT_REACHED": 409,
    "ERR_RESERVATION_BLOCKS_RENEWAL": 409,
    "ERR_LOAN_RECALLED": 409,
    "ERR_HOLD_EXPIRED": 409,
    "ERR_INVALID_WAIVER": 422,
    "ERR_FINE_OVERPAYMENT": 409,
    "ERR_UNKNOWN_PARTNER": 422,
    "ERR_ILL_LOAN_PERIOD_NOT_MET": 409,
    "ERR_DUPLICATE_RESERVATION": 409,
    "ERR_PAYMENT_EVENT_MISSING": 409,
}


def err(error_id: str, message: str = "") -> APIError:
    return APIError(error_id, message or error_id, ERROR_CATALOG.get(error_id, 500))
