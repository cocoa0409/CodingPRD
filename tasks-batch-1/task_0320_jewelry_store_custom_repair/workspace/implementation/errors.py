"""Error classes and error-ID -> HTTP status mapping (PRD §5 error catalogue)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or error_id


# PRD §5 Error Code Catalogue (verbatim error_id -> HTTP status).
ERROR_STATUS = {
    "ERR_MISSING_AUTH": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_DUPLICATE": 409,
    "ERR_PAYMENT_TARGET_MISMATCH": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_ITEM_NOT_AVAILABLE": 409,
    "ERR_ITEM_SOLD": 409,
    "ERR_CUSTOMER_SUSPENDED": 409,
    "ERR_NO_COVERAGE": 409,
    "ERR_MAX_REVISIONS_REACHED": 409,
    "ERR_LINE_ITEMS_REQUIRED": 422,
    "ERR_NO_PARTS_NEEDED": 409,
    "ERR_BENCH_CONFLICT": 409,
    "ERR_APPRAISAL_SLOT_CONFLICT": 409,
    "ERR_DEPOSIT_REQUIRED": 402,
    "ERR_BALANCE_OUTSTANDING": 402,
    "ERR_STALE_VERSION": 412,
    "ERR_VERSION_REQUIRED": 422,
}
