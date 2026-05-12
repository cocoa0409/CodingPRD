"""Error definitions and exceptions (per PRD §5 / scaffold §1.6)."""


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error catalog: error_id -> http_status.
ERROR_CATALOG = {
    "ERR_AUTH_REQUIRED": 401,
    "ERR_PERMISSION_DENIED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_EVIDENCE_NOT_CONFIRMED": 409,
    "ERR_HASH_FORMAT_INVALID": 422,
    "ERR_BATCH_MEMBER_INVALID": 422,
    "ERR_BATCH_SIZE_OUT_OF_RANGE": 422,
    "ERR_PERIOD_INVALID": 422,
    "ERR_RESUBMIT_LIMIT_EXCEEDED": 409,
    "ERR_TIMESTAMP_REQUIRED": 409,
    "ERR_CERTIFICATE_REQUIRED": 409,
    "ERR_EVIDENCE_EXPIRED": 410,
    "ERR_INSUFFICIENT_BALANCE": 402,
    "ERR_DUPLICATE_IDEMPOTENCY_KEY": 409,
    "ERR_DUPLICATE_PAYMENT_REF": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_INVOICE_SCOPE_INVALID": 422,
    "ERR_VALIDATION_FAILED": 422,
}


def err(error_id: str, message: str = "") -> APIError:
    """Construct an APIError using the catalog HTTP status."""
    if error_id not in ERROR_CATALOG:
        return APIError(error_id, message or error_id, 422)
    return APIError(error_id, message or error_id, ERROR_CATALOG[error_id])
