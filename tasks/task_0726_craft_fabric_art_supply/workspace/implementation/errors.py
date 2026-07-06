class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: id -> http status
ERRORS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_WORKSHOP_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_REGISTRATION_NOT_FOUND": 404,
    "ERR_FRAMING_NOT_FOUND": 404,
    "ERR_SPECIAL_ORDER_NOT_FOUND": 404,
    "ERR_REFERENCED_ENTITY_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_EMPTY_ORDER": 409,
    "ERR_INSUFFICIENT_INVENTORY": 409,
    "ERR_ORDER_NOT_PAID": 409,
    "ERR_CUT_NOT_RECORDED": 409,
    "ERR_INSUFFICIENT_POINTS": 409,
    "ERR_INVALID_CUT_INCREMENT": 422,
    "ERR_ROOM_CONFLICT": 409,
    "ERR_CUSTOMER_SESSION_OVERLAP": 409,
    "ERR_REGISTRATION_CLOSED": 422,
    "ERR_COUPON_EXPIRED": 422,
    "ERR_COUPON_NOT_STACKABLE": 422,
    "ERR_COUPON_MIN_NOT_MET": 422,
    "ERR_LINKED_ORDER_NOT_READY": 409,
    "ERR_NO_SESSIONS": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS.get(error_id, 400), message)
