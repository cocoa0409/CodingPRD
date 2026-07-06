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
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 422,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_NOT_OWNER": 403,
    "ERR_NO_QUALIFIED_INTERPRETER": 409,
    "ERR_OFFER_EXPIRED": 409,
    "ERR_INTERPRETER_DOUBLE_BOOKED": 409,
    "ERR_CLIENT_WINDOW_CONFLICT": 409,
    "ERR_INTERPRETER_AT_CAPACITY": 409,
    "ERR_ALREADY_RATED": 409,
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
    "ERR_STALE_REQUEST_VERSION": 412,
    "ERR_CLIENT_SUSPENDED": 403,
    "ERR_INVALID_WINDOW": 400,
    "ERR_SESSION_NOT_ENDED": 409,
    "ERR_NO_RATE_PLAN": 409,
    "ERR_INVALID_NO_SHOW_PARTY": 400,
    "ERR_INVALID_CORRECTED_UNITS": 400,
    "ERR_SESSION_ALREADY_INVOICED": 409,
    "ERR_INVOICE_NOT_DRAFT": 409,
    "ERR_INVOICE_NOT_ISSUED": 409,
    "ERR_NOTHING_TO_INVOICE": 409,
    "ERR_INTERPRETER_DEACTIVATED": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
