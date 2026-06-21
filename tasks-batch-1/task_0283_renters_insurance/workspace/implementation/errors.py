"""Error catalog. Error IDs and HTTP statuses are taken verbatim from PRD §5
and SCAFFOLD §1.6."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status for every error id (PRD §5 Error Code Catalogue).
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_POLICY_NOT_EDITABLE": 409,
    "ERR_POLICY_NOT_ACTIVE": 409,
    "ERR_POLICY_NOT_BILLABLE": 409,
    "ERR_STALE_POLICY_VERSION": 412,
    "ERR_DUPLICATE_COVERAGE_TYPE": 409,
    "ERR_COVERAGE_INCOMPLETE": 422,
    "ERR_INVALID_TERM": 422,
    "ERR_TERM_OVERLAP": 409,
    "ERR_LOSS_OUTSIDE_TERM": 422,
    "ERR_DISPLACEMENT_OVERLAP": 409,
    "ERR_COVERAGE_TYPE_MISMATCH": 422,
    "ERR_CLAIM_EMPTY": 422,
    "ERR_LIMIT_EXCEEDED": 422,
    "ERR_DENIAL_REASON_REQUIRED": 422,
    "ERR_APPEAL_LIMIT_REACHED": 409,
    "ERR_OPEN_CLAIM_BLOCKS_CANCEL": 409,
    "ERR_NO_OVERDUE_INVOICE": 409,
    "ERR_NOT_YET_LAPSABLE": 409,
    "ERR_NOT_YET_EXPIRED": 409,
    "ERR_LAPSE_BALANCE_OUTSTANDING": 409,
    "ERR_REINSTATE_FEE_UNPAID": 402,
    "ERR_REINSTATE_WINDOW_CLOSED": 409,
    "ERR_PAYMENT_NOT_VOIDABLE": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)
