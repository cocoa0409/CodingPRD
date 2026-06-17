"""Error catalogue and the ApiError exception.

Every error_id and HTTP status here traces to PRD §5 (Error Code Catalogue)
and SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> http_status (PRD §5 / scaffold §1.6)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_FEE_MODEL_FIELDS": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_PROJECT_FROZEN": 409,
    "ERR_BUDGET_GATE": 409,
    "ERR_VENDOR_SUSPENDED": 409,
    "ERR_VENDOR_WINDOW_CONFLICT": 409,
    "ERR_ORDER_EMPTY": 409,
    "ERR_SELECTION_ALREADY_ORDERED": 409,
    "ERR_SELECTION_ON_ORDER": 409,
    "ERR_FFE_ITEM_INACTIVE": 409,
    "ERR_ROOM_NOT_APPROVED": 409,
    "ERR_ROOMS_NOT_APPROVED": 409,
    "ERR_OPEN_REVISION": 409,
    "ERR_NO_ORDERS_IN_FLIGHT": 409,
    "ERR_ORDERS_OPEN": 409,
    "ERR_NO_PRESENTED_MOODBOARD": 409,
    "ERR_MOODBOARD_ALREADY_PRESENTED": 409,
    "ERR_SPEC_NOTE_REQUIRED": 409,
    "ERR_PUNCH_ITEMS_OPEN": 409,
    "ERR_RETURN_NOT_JUSTIFIED": 409,
    "ERR_FEE_MODEL_MISMATCH": 409,
    "ERR_DUPLICATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_VALIDATION": 400,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
