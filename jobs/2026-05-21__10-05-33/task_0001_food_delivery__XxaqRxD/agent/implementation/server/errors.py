"""Error catalogue. Each error maps to an HTTP status code per PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id: str, message: str | None = None, status: int | None = None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)
        self.status = status if status is not None else _STATUS[error_id]


_STATUS = {
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


_DEFAULT_MESSAGES = {
    "ERR_AUTH_REQUIRED": "Missing or invalid authentication headers.",
    "ERR_FORBIDDEN": "Caller is not permitted to perform this action.",
    "ERR_NOT_FOUND": "Resource not found.",
    "ERR_INVALID_STATE": "Resource is not in a state from which this transition is allowed.",
    "ERR_VERSION_CONFLICT": "Optimistic concurrency conflict: supplied version does not match.",
    "ERR_ORDER_ALREADY_ASSIGNED": "Order is already assigned to another rider.",
    "ERR_DUPLICATE_RETURN": "A return for this order is already open.",
    "ERR_RESTAURANT_UNAVAILABLE": "Restaurant or one of the menu items is unavailable.",
    "ERR_SUSPEND_CRITERIA_NOT_MET": "Rider does not meet the suspension criteria.",
    "ERR_RETURN_WINDOW_EXPIRED": "Return window has expired.",
    "ERR_REFUND_AMOUNT_INVALID": "Refund amount is outside the allowed range.",
    "ERR_ORDER_INVALID": "Order payload is invalid.",
    "ERR_RELATED_RETURN_UNRESOLVED": "Linked return is not yet resolved.",
    "ERR_VALIDATION": "Request payload is malformed or missing required fields.",
}
