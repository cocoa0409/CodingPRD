"""Error catalog and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: id -> http status
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_NO_BREACHED_COVENANT": 409,
    "ERR_KYC_NOT_CLEARED": 409,
    "ERR_COVENANT_SET_INCOMPLETE": 409,
    "ERR_NO_ACTIVE_INDEX": 409,
    "ERR_LIEN_POSITION_CONFLICT": 409,
    "ERR_DRAW_PERIOD_NOT_ELAPSED": 409,
    "ERR_DRAWS_NOT_PERMITTED": 409,
    "ERR_INSUFFICIENT_CREDIT": 422,
    "ERR_OVERPAYMENT": 422,
    "ERR_BALANCE_NOT_ZERO": 409,
    "ERR_FEES_OUTSTANDING": 409,
    "ERR_REVERSAL_UNDERFLOW": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_REQUEST": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
