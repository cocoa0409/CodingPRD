"""Error catalog. Error IDs and HTTP statuses taken verbatim from the PRD/scaffold."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status by error id (from PRD §5 / scaffold Table 6)
ERROR_STATUS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT": 401,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_CROSS_SHOP_REFERENCE": 409,
    "ERR_NO_SPECS": 409,
    "ERR_FINISH_REQUIRED": 409,
    "ERR_MACHINE_OFFLINE": 409,
    "ERR_MACHINE_TIME_CONFLICT": 409,
    "ERR_INSTALL_CAPACITY_FULL": 409,
    "ERR_INSUFFICIENT_STOCK": 409,
    "ERR_DEPOSIT_UNPAID": 409,
    "ERR_CUSTOMER_CREDIT_HOLD": 409,
    "ERR_EMPTY_DRAW": 409,
    "ERR_BUILD_INCOMPLETE": 409,
    "ERR_CHANGE_OPEN": 409,
    "ERR_MAJOR_PUNCH_OPEN": 409,
    "ERR_PUNCH_OPEN": 409,
    "ERR_NOTHING_TO_REOPEN": 409,
    "ERR_BALANCE_OUTSTANDING": 409,
    "ERR_DEPOSIT_PAID_NO_CANCEL": 409,
    "ERR_RESERVATION_LOCKED": 409,
    "ERR_SPECS_LOCKED": 409,
    "ERR_PROJECT_NOT_READY": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_VALIDATION_PAGINATION": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
