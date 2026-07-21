"""Error catalog and ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id -> http status (from PRD section 5 error catalogue).
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 400,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_RENTAL_UNIT_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    "ERR_TRIP_NOT_FOUND": 404,
    "ERR_GUIDE_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_TRADE_IN_NOT_FOUND": 404,
    "ERR_REPAIR_ORDER_NOT_FOUND": 404,
    "ERR_SPECIAL_ORDER_NOT_FOUND": 404,
    "ERR_PURCHASE_NOT_FOUND": 404,
    "ERR_DECLARATION_NOT_FOUND": 404,
    "ERR_PASS_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_TRIP_NOT_OPEN": 409,
    "ERR_MEMBERSHIP_NOT_ACTIVE": 409,
    "ERR_RENTAL_UNIT_UNAVAILABLE": 409,
    "ERR_GUIDE_NOT_CERTIFIED": 409,
    "ERR_RENTAL_WINDOW_CONFLICT": 409,
    "ERR_GUIDE_SCHEDULE_CONFLICT": 409,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_TRIP_FULL": 409,
    "ERR_INVALID_QUANTITY": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_TRADE_IN_ROUNDS_EXCEEDED": 409,
    "ERR_INSUFFICIENT_POINTS": 402,
    "ERR_INSUFFICIENT_WALLET": 402,
    "ERR_REPAIR_UNSETTLED": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)
