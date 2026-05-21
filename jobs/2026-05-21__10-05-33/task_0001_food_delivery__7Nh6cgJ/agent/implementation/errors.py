"""Error catalogue and exception class."""

from __future__ import annotations

ERROR_STATUSES = {
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


class APIError(Exception):
    def __init__(self, error_id: str, message: str | None = None) -> None:
        if error_id not in ERROR_STATUSES:
            raise ValueError(f"Unknown error id: {error_id}")
        self.error_id = error_id
        self.status = ERROR_STATUSES[error_id]
        self.message = message or _default_message(error_id)
        super().__init__(self.message)


def _default_message(error_id: str) -> str:
    return {
        "ERR_AUTH_REQUIRED": "Authentication headers missing or invalid.",
        "ERR_FORBIDDEN": "Caller is not permitted to perform this operation.",
        "ERR_NOT_FOUND": "Resource not found.",
        "ERR_INVALID_STATE": "Requested transition is not allowed from the current state.",
        "ERR_VERSION_CONFLICT": "Version mismatch on optimistic concurrency check.",
        "ERR_ORDER_ALREADY_ASSIGNED": "Order is already assigned to another rider.",
        "ERR_DUPLICATE_RETURN": "An open return already exists for this order.",
        "ERR_RESTAURANT_UNAVAILABLE": "Restaurant or menu item is not available.",
        "ERR_SUSPEND_CRITERIA_NOT_MET": "Rider does not meet the criteria required for suspension.",
        "ERR_RETURN_WINDOW_EXPIRED": "Return window has expired.",
        "ERR_REFUND_AMOUNT_INVALID": "Refund amount is outside the allowed range.",
        "ERR_ORDER_INVALID": "Order payload failed domain validation.",
        "ERR_RELATED_RETURN_UNRESOLVED": "Linked return is not in a terminal state.",
        "ERR_VALIDATION": "Request body failed validation.",
    }[error_id]
