"""Error catalogue — error_id, HTTP status pairs from PRD Section 5 / scaffold §1.6."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error ID -> HTTP status (PRD Section 5)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_LOAN_VERSION": 412,
    "ERR_LOAN_NOT_IN_DEFAULT": 409,
    "ERR_LIEN_LOAN_NOT_OUTSTANDING": 409,
    "ERR_DEVICE_LOAN_NOT_DELINQUENT": 409,
    "ERR_APR_CAP_EXCEEDED": 422,
    "ERR_TERM_OUT_OF_BOUNDS": 422,
    "ERR_RENEWAL_LIMIT_REACHED": 409,
    "ERR_REDEMPTION_GRACE_ACTIVE": 409,
    "ERR_COMMAND_WINDOW_OVERLAP": 409,
    "ERR_ASSIGNMENT_WINDOW_OVERLAP": 409,
    "ERR_LTV_EXCEEDED": 422,
    "ERR_INSUFFICIENT_PAYMENT": 422,
    "ERR_ACTIVE_REPO_EXISTS": 409,
    "ERR_VALIDATION_RANGE": 422,
    "ERR_BORROWER_BARRED": 403,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
