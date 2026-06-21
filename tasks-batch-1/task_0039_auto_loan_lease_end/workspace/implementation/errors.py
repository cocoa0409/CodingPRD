class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error catalog: id -> http status
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_NO_ACTIVE_RATE_CARD": 409,
    "ERR_VEHICLE_UNAVAILABLE": 409,
    "ERR_LOAN_NOT_PAYABLE": 409,
    "ERR_LOAN_TERM_COMPLETE": 409,
    "ERR_LEASE_NOT_MATURABLE": 409,
    "ERR_LEASE_NOT_ELECTABLE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_DEFAULT_THRESHOLD_NOT_MET": 409,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 409,
    "ERR_PAYOFF_AMOUNT_MISMATCH": 409,
    "ERR_MILEAGE_SCHEDULE_INVALID": 422,
    "ERR_RENEW_TERM_INVALID": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, message or error_id, ERRORS[error_id])
