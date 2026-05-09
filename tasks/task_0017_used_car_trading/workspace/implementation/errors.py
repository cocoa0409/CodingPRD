"""Error catalog and APIError exception."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


# Error catalog (id -> http status)
ERROR_CATALOG = {
    "ERR_AUTH_MISSING": 401,
    "ERR_AUTH_INVALID": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_NOT_OWNER": 403,
    "ERR_INVALID_STATE": 409,
    "ERR_VIN_INVALID": 422,
    "ERR_ASSESSMENT_NOT_FINALIZED": 422,
    "ERR_ASSESSMENT_VERSION_STALE": 409,
    "ERR_LISTING_DOCS_INSUFFICIENT": 422,
    "ERR_BID_TOO_LOW": 422,
    "ERR_LISTING_NOT_RESERVABLE": 409,
    "ERR_RESERVATION_QUEUED_NOT_HOLDING": 409,
    "ERR_DEPOSIT_LIMIT_EXCEEDED": 422,
    "ERR_DOWN_PAYMENT_INSUFFICIENT": 422,
    "ERR_LOAN_PARAMS_INVALID": 422,
    "ERR_APPOINTMENT_OUT_OF_WINDOW": 422,
    "ERR_TRANSFER_DOCS_INCOMPLETE": 422,
    "ERR_WARRANTY_NOT_ACTIVE": 409,
    "ERR_COMPONENT_NOT_COVERED": 422,
    "ERR_DISPUTE_ROUNDS_EXHAUSTED": 409,
    "ERR_DISPUTE_NOT_ELIGIBLE": 422,
    "ERR_IDEMPOTENCY_REPLAY": 200,
    "ERR_PAGINATION_INVALID": 400,
    "ERR_VERSION_CONFLICT": 409,
}


def err(error_id: str, message: str = "") -> APIError:
    return APIError(error_id, ERROR_CATALOG[error_id], message or error_id)
