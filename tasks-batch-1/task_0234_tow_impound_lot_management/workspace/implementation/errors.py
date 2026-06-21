"""Error classes and the error catalog (id -> HTTP status)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id


# Error id -> HTTP status, straight from PRD §5 / scaffold §1.6.
ERROR_STATUS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_REFERENCE_MISMATCH": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_INVENTORY_REQUIRED": 409,
    "ERR_HOLD_ACTIVE": 409,
    "ERR_NO_HOLD": 409,
    "ERR_WAIVER_PENDING": 409,
    "ERR_BALANCE_UNPAID": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_STATUTORY_PERIOD_NOT_ELAPSED": 409,
    "ERR_NO_LIENHOLDER": 409,
    "ERR_METHOD_NOT_CERTIFIED": 409,
    "ERR_OFFER_EXPIRED": 409,
    "ERR_OFFER_NOT_EXPIRED": 409,
    "ERR_PROVIDER_NOT_ACTIVE": 409,
    "ERR_NO_ELIGIBLE_PROVIDER": 409,
    "ERR_LOT_SUSPENDED": 409,
    "ERR_AUCTION_WINDOW_OVERLAP": 409,
    "ERR_AUCTION_WINDOW_NOT_STARTED": 409,
    "ERR_ALREADY_IN_AUCTION": 409,
    "ERR_NOT_IN_AUCTION": 409,
    "ERR_STALE_LOT_VERSION": 412,
}
