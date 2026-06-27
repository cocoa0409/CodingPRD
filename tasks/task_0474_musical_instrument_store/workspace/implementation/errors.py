"""Error catalogue and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue: error_id -> http_status
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_SERIAL": 409,
    "ERR_RESERVATION_MISMATCH": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_PLAN_NOT_RENT_TO_OWN": 409,
    "ERR_PAYOFF_MISMATCH": 422,
    "ERR_OUTSTANDING_LATE_FEES": 409,
    "ERR_CREDIT_TOO_LOW": 422,
    "ERR_DEPOSIT_INSUFFICIENT": 422,
    "ERR_LAYAWAY_NOT_PAID": 422,
    "ERR_TICKET_NOT_ASSIGNED": 403,
    "ERR_VALIDATION": 400,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
