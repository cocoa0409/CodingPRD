"""Error catalogue — error_id → HTTP status code and the ApiError exception."""


ERROR_STATUS = {
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


class ApiError(Exception):
    def __init__(self, error_id: str, message: str | None = None):
        if error_id not in ERROR_STATUS:
            raise RuntimeError(f"unknown error_id {error_id}")
        self.error_id = error_id
        self.message = message or error_id
        super().__init__(self.message)

    @property
    def status_code(self) -> int:
        return ERROR_STATUS[self.error_id]
