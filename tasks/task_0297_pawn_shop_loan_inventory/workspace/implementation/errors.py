"""Error classes and the error catalog (PRD §5 / SCAFFOLD §1.6)."""


class ApiError(Exception):
    """Carries the machine-readable error_id, HTTP status, and message."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog: error_id -> http_status (PRD §5 / SCAFFOLD §1.6) ---
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_POLICE_HOLD_ACTIVE": 409,
    "ERR_CUSTOMER_FLAGGED": 409,
    "ERR_GRACE_NOT_ELAPSED": 409,
    "ERR_BIN_CAPACITY_EXCEEDED": 409,
    "ERR_LAYAWAY_RESERVATION_CONFLICT": 409,
    "ERR_PERIOD_CAP_EXCEEDED": 409,
    "ERR_LOAN_ALREADY_SERVICED": 409,
    "ERR_PRICE_BELOW_FLOOR": 422,
    "ERR_INSTALLMENT_MISMATCH": 422,
    "ERR_PRINCIPAL_NON_POSITIVE": 422,
    "ERR_STALE_LOAN_VERSION": 412,
    "ERR_ITEM_NOT_APPRAISED": 409,
    "ERR_DUPLICATE_GOV_ID": 409,
    "ERR_DUPLICATE_SCHEDULE": 409,
    "ERR_VALIDATION_PAGINATION": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
