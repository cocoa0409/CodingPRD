class APIError(Exception):
    def __init__(self, error_id: str, message: str, status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.status = status


_CODES = {
    "ERR_AUTH_REQUIRED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_ORDER_ALREADY_ASSIGNED": 409,
    "ERR_DUPLICATE_RETURN": 409,
    "ERR_RESTAURANT_UNAVAILABLE": 422,
    "ERR_SUSPEND_CRITERIA_NOT_MET": 422,
    "ERR_RETURN_WINDOW_EXPIRED": 422,
    "ERR_REFUND_AMOUNT_INVALID": 422,
    "ERR_ORDER_INVALID": 422,
    "ERR_RELATED_RETURN_UNRESOLVED": 422,
    "ERR_VALIDATION": 422,
}


def err(error_id: str, message: str = "") -> APIError:
    status = _CODES.get(error_id, 422)
    if not message:
        message = error_id
    return APIError(error_id, message, status)
