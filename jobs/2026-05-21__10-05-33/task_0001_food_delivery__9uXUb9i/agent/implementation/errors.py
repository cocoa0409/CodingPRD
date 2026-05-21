"""ApiError exception and the error code -> HTTP status mapping (PRD §5)."""
from __future__ import annotations


ERROR_HTTP_STATUS: dict[str, int] = {
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
    def __init__(self, error_id: str, message: str | None = None) -> None:
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.status = ERROR_HTTP_STATUS.get(error_id, 500)
        super().__init__(self.message)


def _default_message(error_id: str) -> str:
    return {
        "ERR_AUTH_REQUIRED": "Authentication headers missing or role not recognized.",
        "ERR_FORBIDDEN": "Caller is not permitted to perform this action.",
        "ERR_NOT_FOUND": "Resource not found.",
        "ERR_INVALID_STATE": "Resource is not in a state that allows this transition.",
        "ERR_VERSION_CONFLICT": "Resource version does not match the supplied value.",
        "ERR_ORDER_ALREADY_ASSIGNED": "Order is already assigned to another rider.",
        "ERR_DUPLICATE_RETURN": "An active return already exists for this order.",
        "ERR_RESTAURANT_UNAVAILABLE": "Restaurant or menu item not available for ordering.",
        "ERR_SUSPEND_CRITERIA_NOT_MET": "Rider performance metrics do not meet suspension criteria.",
        "ERR_RETURN_WINDOW_EXPIRED": "The 24-hour return window has expired.",
        "ERR_REFUND_AMOUNT_INVALID": "Refund amount is out of the permitted range.",
        "ERR_ORDER_INVALID": "Order body is invalid.",
        "ERR_RELATED_RETURN_UNRESOLVED": "Linked return must be resolved before this ticket can be resolved.",
        "ERR_VALIDATION": "Request payload failed validation.",
    }.get(error_id, "Error.")
