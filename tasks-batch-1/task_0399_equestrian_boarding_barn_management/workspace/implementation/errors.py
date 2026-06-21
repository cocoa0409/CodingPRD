"""Error class and the full error catalog (PRD §5 / scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: id -> http status. Verbatim from PRD §5 error table.
ERROR_CATALOG = {
    "ERR_MISSING_USER_CONTEXT": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_REQUEST": 422,
    "ERR_OWNER_NOT_FOUND": 404,
    "ERR_WAIVER_NOT_FOUND": 404,
    "ERR_STALL_NOT_FOUND": 404,
    "ERR_HORSE_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_LESSON_NOT_FOUND": 404,
    "ERR_VISIT_NOT_FOUND": 404,
    "ERR_ENTRY_NOT_FOUND": 404,
    "ERR_TURNOUT_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_WAIVER_NOT_SIGNABLE": 409,
    "ERR_WAIVER_NOT_ACTIVE": 409,
    "ERR_AGREEMENT_NOT_ACTIVE": 409,
    "ERR_BOARDING_NOT_ACTIVE": 409,
    "ERR_INVOICE_NOT_OPEN": 409,
    "ERR_INVOICE_NOT_FINALIZED": 409,
    "ERR_CANCEL_TOO_LATE": 409,
    "ERR_VISIT_OVERLAP": 409,
    "ERR_PASTURE_FULL": 409,
    "ERR_STALL_FULL": 409,
    "ERR_TURNOUT_IN_PAST": 409,
    "ERR_OWNER_DELINQUENT": 409,
    "ERR_INVOICE_HAS_PAYMENTS": 409,
    "ERR_NO_BILLABLE_LINES": 409,
    "ERR_OVERPAYMENT": 422,
    "ERR_INSUFFICIENT_DEPOSIT": 422,
    "ERR_STALE_OWNER_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
