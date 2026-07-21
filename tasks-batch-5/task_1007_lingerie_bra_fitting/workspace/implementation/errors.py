"""Error catalogue (PRD Section 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)


# error_id -> HTTP status, transcribed verbatim from PRD Section 5 / SCAFFOLD §1.6
ERROR_HTTP = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    # validation
    "ERR_VALIDATION": 400,
    "ERR_MEASUREMENT_OUT_OF_RANGE": 422,
    # not found
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_FITTER_NOT_FOUND": 404,
    "ERR_ROOM_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_SKU_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_ORDER_LINE_NOT_FOUND": 404,
    "ERR_EXCHANGE_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_REMINDER_NOT_FOUND": 404,
    # state
    "ERR_INVALID_STATE": 409,
    "ERR_EMPTY_ORDER": 409,
    "ERR_ORDER_NOT_PLACED": 409,
    "ERR_ORDER_NOT_PAID": 409,
    "ERR_ORDER_NOT_CANCELLABLE": 409,
    "ERR_FIT_NOT_SUBMITTED": 409,
    "ERR_LINE_NOT_EXCHANGEABLE_STATE": 409,
    "ERR_NOTHING_TO_REIMBURSE": 409,
    "ERR_STALE_APPOINTMENT_VERSION": 412,
    # business safety
    "ERR_FITTER_NOT_CERTIFIED": 409,
    "ERR_ROOM_NOT_PRIVATE": 409,
    "ERR_ITEM_NOT_EXCHANGEABLE_HYGIENE": 409,
    # scheduling
    "ERR_FITTER_DOUBLE_BOOKED": 409,
    "ERR_ROOM_AT_CAPACITY": 409,
    # temporal
    "ERR_EXCHANGE_WINDOW_EXPIRED": 409,
    "ERR_REMINDER_NOT_DUE": 409,
    # referential
    "ERR_SKU_INACTIVE": 409,
    "ERR_NOT_MASTECTOMY_ORDER": 409,
    # fiscal
    "ERR_INSUFFICIENT_STOCK": 402,
}
