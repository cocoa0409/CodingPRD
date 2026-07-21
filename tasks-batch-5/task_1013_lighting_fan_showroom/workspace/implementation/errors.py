"""Error catalog and ApiError exception (§1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id, http_status)
ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_ACCOUNT_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_ORDER_NOT_DRAFT": 409,
    "ERR_ORDER_NOT_CONFIRMED": 409,
    "ERR_DELIVERY_NOT_READY": 409,
    "ERR_INSTALLER_UNAVAILABLE": 409,
    "ERR_TRUCK_WINDOW_CONFLICT": 409,
    "ERR_NO_ELIGIBLE_ITEMS": 422,
    "ERR_REBATE_BUDGET_EXCEEDED": 409,
    "ERR_LINE_NOT_RETURNABLE": 409,
    "ERR_INSUFFICIENT_CREDIT": 402,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERR[error_id], message)
