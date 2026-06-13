"""Error catalogue and the ApiError exception type.

Error IDs and HTTP statuses are taken verbatim from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error ID -> HTTP status (PRD §5 Error Code Catalogue / SCAFFOLD §1.6).
ERROR_STATUS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT": 400,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_ORDER_NOT_DRAFT": 409,
    "ERR_PROOF_NOT_APPROVED": 409,
    "ERR_ORDER_EMPTY": 409,
    "ERR_BLANK_INSUFFICIENT": 409,
    "ERR_ORDER_NOT_CONFIRMED": 409,
    "ERR_PRESS_WINDOW_CONFLICT": 409,
    "ERR_STATION_OVERSUBSCRIBED": 409,
    "ERR_INVALID_GOOD_UNITS": 400,
    "ERR_RUN_SHORT": 409,
    "ERR_ORDER_NOT_FULFILLED": 409,
    "ERR_ALREADY_INVOICED": 409,
    "ERR_NOT_INVOICED": 409,
    "ERR_ORDER_NOT_CANCELLABLE": 409,
    "ERR_INVALID_REORDER_SOURCE": 409,
    "ERR_STALE_ORDER_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
