"""Error classes and error-id/HTTP-status catalog."""


class APIError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http_status
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_POLICY_ALREADY_ACTIVE": 409,
    "ERR_POLICY_IN_USE": 409,
    "ERR_NO_ACTIVE_POLICY": 409,
    "ERR_TRIP_DATE_OVERLAP": 409,
    "ERR_TRIP_NOT_APPROVED": 409,
    "ERR_REPORT_EMPTY": 409,
    "ERR_RECEIPT_REQUIRED": 409,
    "ERR_RECEIPT_AMOUNT_MISMATCH": 409,
    "ERR_LODGING_OVERLAP": 409,
    "ERR_CARD_NOT_ACTIVE": 409,
    "ERR_CARD_LIMIT_EXCEEDED": 409,
    "ERR_CARD_HAS_OPEN_HOLDS": 409,
    "ERR_OOP_CHAIN_INCOMPLETE": 409,
    "ERR_OOP_STEP_OUT_OF_ORDER": 409,
    "ERR_BUDGET_EXCEEDED": 409,
    "ERR_RETURN_REASON_REQUIRED": 422,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    """Build an APIError using the catalog's HTTP status."""
    return APIError(error_id, ERROR_CATALOG[error_id], message)
