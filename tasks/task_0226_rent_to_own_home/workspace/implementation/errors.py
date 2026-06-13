"""Error catalog and the ApiError exception.

Error IDs and HTTP statuses are taken verbatim from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id -> http_status), per PRD §5 error catalogue.
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_REFERENCE_MISMATCH": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_PROPERTY_NOT_AVAILABLE": 409,
    "ERR_AGREEMENT_NOT_ACTIVE": 409,
    "ERR_AGREEMENT_NOT_EXERCISED": 409,
    "ERR_OPTION_EXPIRED": 409,
    "ERR_OPTION_NOT_YET_EXPIRED": 409,
    "ERR_OPTION_BLOCKED_BY_DEFAULT": 409,
    "ERR_DEFAULT_THRESHOLD_NOT_MET": 409,
    "ERR_CREDIT_SCORE_TOO_LOW": 409,
    "ERR_DUPLICATE_PERIOD": 409,
    "ERR_PAYMENT_NOT_PENDING": 409,
    "ERR_PAYMENT_NOT_LATE": 409,
    "ERR_TICKET_NOT_OPEN": 409,
    "ERR_TICKET_NOT_APPROVED": 409,
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)
