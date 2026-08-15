"""API error type carrying the scaffold's exact error_id and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Error catalog (id -> http status), verbatim from PRD section 5.
ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_RENTER_SCOPE_VIOLATION": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_RENTER_SUSPENDED": 409,
    "ERR_INSURANCE_NOT_VERIFIED": 422,
    "ERR_INSUFFICIENT_COVERAGE": 422,
    "ERR_CERTIFICATE_EXPIRED": 422,
    "ERR_ALTERATION_PROHIBITED": 422,
    "ERR_RESTORATION_INCOMPLETE": 409,
    "ERR_ITEM_NOT_RENTABLE": 409,
    "ERR_ITEM_HAS_ACTIVE_HOLDS": 409,
    "ERR_RATE_CARD_REQUIRED": 409,
    "ERR_WINDOW_OUT_OF_BOUNDS": 422,
    "ERR_DATE_ORDER": 422,
    "ERR_QUANTITY_INVALID": 400,
    "ERR_HOLD_EXPIRED": 409,
    "ERR_CAPACITY_EXCEEDED": 409,
    "ERR_NO_UNITS_AVAILABLE": 409,
    "ERR_NOTHING_TO_PULL": 409,
    "ERR_LINES_NOT_PICKED": 409,
    "ERR_RESERVATION_IN_USE": 409,
    "ERR_PRODUCTION_HAS_ACTIVE_PULLS": 409,
    "ERR_DEACCESSION_BLOCKED": 409,
    "ERR_DUPLICATE_BARCODE": 409,
    "ERR_CLAIM_ALREADY_EXISTS": 409,
    "ERR_CLAIM_TYPE_MISMATCH": 409,
    "ERR_CLAIM_ALREADY_BILLED": 409,
    "ERR_SOD_VIOLATION": 403,
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
    "ERR_INVOICE_EMPTY": 409,
    "ERR_PAYMENT_INVALID": 422,
    "ERR_PAYMENT_EXCEEDS_BALANCE": 422,
    "ERR_CREDIT_INVALID": 422,
    "ERR_CREDIT_EXCEEDS_BALANCE": 422,
}


def fail(error_id, message):
    raise ApiError(error_id, ERR[error_id], message)
