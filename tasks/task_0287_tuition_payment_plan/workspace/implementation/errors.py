"""Error classes and error ID constants (PRD Section 5 error catalogue)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue: error_id -> http_status (PRD §5)
ERROR_CATALOG = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_AMOUNT": 400,
    "ERR_INVALID_TERM_WINDOW": 400,
    "ERR_INVALID_PLAN_TEMPLATE": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_TERM_NOT_OPEN": 409,
    "ERR_OUTSIDE_ENROLL_WINDOW": 409,
    "ERR_TEMPLATE_RETIRED": 409,
    "ERR_STUDENT_ON_HOLD": 409,
    "ERR_NO_CHARGES_TO_FINANCE": 409,
    "ERR_AUTOPAY_REQUIRED": 409,
    "ERR_ENROLLMENT_NOT_ACTIVE": 409,
    "ERR_DOWN_PAYMENT_ALREADY_PAID": 409,
    "ERR_INSTALLMENT_NOT_PAYABLE": 409,
    "ERR_NO_SCHEDULED_INSTALLMENTS": 409,
    "ERR_DELINQUENCY_UNRESOLVED": 409,
    "ERR_TERM_HAS_OPEN_BALANCES": 409,
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
