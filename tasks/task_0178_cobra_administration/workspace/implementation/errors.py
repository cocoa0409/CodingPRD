"""Error catalog — error_id -> HTTP status, and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status if http_status is not None else ERROR_STATUS.get(error_id, 400)


# error_id -> HTTP status (from PRD §5 / SCAFFOLD errors table)
ERROR_STATUS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_BENEFICIARY_NOT_ELIGIBLE": 409,
    "ERR_ELECTION_WINDOW_CLOSED": 409,
    "ERR_DISABILITY_WINDOW_INVALID": 409,
    "ERR_EXTENSION_NOT_APPLICABLE": 409,
    "ERR_INVALID_TERMINATION_REASON": 409,
    "ERR_INVALID_COVERAGE_MONTH": 409,
    "ERR_DUPLICATE_INVOICE": 409,
    "ERR_NO_OPEN_INVOICE": 409,
    "ERR_INVALID_SUBSIDY_RANGE": 409,
    "ERR_REFUND_EXCEEDS_CREDIT": 409,
    "ERR_NO_CREDIT_BALANCE": 409,
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, message)
