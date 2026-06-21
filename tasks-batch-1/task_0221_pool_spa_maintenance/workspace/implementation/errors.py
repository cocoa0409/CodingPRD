"""Error catalogue and ApiError exception (PRD §5 / scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue: error_id -> http status (PRD §5).
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_NOT_POOL_OWNER": 403,
    "ERR_INVALID_STATE": 409,
    "ERR_FREQUENCY_PLAN_MISMATCH": 422,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_SLOT_OVERLAP": 409,
    "ERR_CRITICAL_REPAIR_BLOCKS_OPEN": 409,
    "ERR_OPEN_VISITS_BLOCK_CLOSE": 409,
    "ERR_EMPTY_ROUTE": 409,
    "ERR_ROUTE_AT_CAPACITY": 409,
    "ERR_SKIP_REASON_REQUIRED": 422,
    "ERR_NOTHING_TO_BILL": 422,
    "ERR_INVOICE_REFERENCE_MISMATCH": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_REQUEST": 422,
}


def err(error_id, message=None):
    """Construct an ApiError using the catalogue's HTTP status."""
    return ApiError(error_id, ERRORS[error_id], message)
