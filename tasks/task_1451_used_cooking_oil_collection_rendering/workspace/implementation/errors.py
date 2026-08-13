"""Error types and the complete error catalog (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Catalog: error_id -> http_status (from SCAFFOLD.yaml errors table / PRD section 5;
# ERR_BATCH_INPUT_MISMATCH is exercised by the batch-intake equality rule of PRD 3.9).
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_CONTAINER_LOCKED": 409,
    "ERR_CONTRACT_NOT_ACTIVE": 409,
    "ERR_SAMPLE_ALREADY_GRADED": 409,
    "ERR_CUSTOMER_SUSPENDED": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_TRUCK_UNAVAILABLE": 409,
    "ERR_SPILL_COMPLAINT_OPEN": 422,
    "ERR_CONTRACT_TERM_OVERLAP": 409,
    "ERR_MANIFEST_DATE_CONFLICT": 409,
    "ERR_TANK_CAPACITY_EXCEEDED": 422,
    "ERR_CONTAINER_CAPACITY_EXCEEDED": 422,
    "ERR_TANK_IMBALANCE": 422,
    "ERR_DUPLICATE_PERIOD": 409,
    "ERR_PICKUP_WINDOW_FUTURE": 422,
    "ERR_PERIOD_NOT_CLOSED": 422,
    "ERR_CONTRACT_IN_COOLING_OFF": 422,
    "ERR_COMPLAINT_REOPEN_WINDOW_EXPIRED": 422,
    "ERR_OPEN_SETTLEMENTS": 422,
    "ERR_GRADE_PENDING": 422,
    "ERR_QUOTE_NOT_PUBLISHED": 422,
    "ERR_THEFT_UNRESOLVED": 409,
    "ERR_PAYOUT_BELOW_MINIMUM": 422,
    "ERR_BATCH_INPUT_MISMATCH": 422,
}


def err(error_id, message):
    """Build an ApiError with the catalogued HTTP status for error_id."""
    return ApiError(error_id, message, ERRORS[error_id])
