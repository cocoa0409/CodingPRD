"""Error catalog: every error_id with its HTTP status, plus the ApiError
exception used to abort requests through the validation pipeline."""

ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_DATE_RANGE": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_REFERENTIAL_INTEGRITY": 422,
    "ERR_SCHEDULE_OVERLAP": 409,
    "ERR_SCHEDULE_GAP": 409,
    "ERR_COVERAGE_OVERLAP": 409,
    "ERR_PROPERTY_OVERCOMMITTED": 409,
    "ERR_ABSTRACTION_NOT_CERTIFIED": 409,
    "ERR_BILLING_NOT_INITIALIZED": 409,
    "ERR_OUTSTANDING_BILLING": 409,
    "ERR_OPEN_RECONCILIATION": 409,
    "ERR_OPEN_CHALLENGE": 409,
    "ERR_POOL_NOT_CLOSED": 409,
    "ERR_LEASE_NOT_ACTIVE": 409,
    "ERR_NOTIFICATION_NOT_YET_DUE": 409,
    "ERR_NOTIFICATION_WINDOW_MISSED": 409,
    "ERR_DATE_PASSED": 409,
    "ERR_NOT_EXERCISABLE": 409,
    "ERR_AMENDMENT_NOT_APPLIED": 409,
    "ERR_EXTENSION_MUST_EXTEND": 409,
    "ERR_EXPANSION_MUST_EXPAND": 409,
    "ERR_CONTRACTION_MUST_CONTRACT": 409,
    "ERR_AUDIT_WINDOW_CLOSED": 409,
    "ERR_MAX_ROUNDS_REACHED": 409,
    "ERR_INVALID_RESOLUTION_SIGN": 409,
    "ERR_RESOLUTION_EXCEEDS_TRUE_UP": 409,
    "ERR_REJECTION_REASON_REQUIRED": 400,
}


class ApiError(Exception):
    def __init__(self, error_id, message):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = ERRORS[error_id]


def err(error_id, message):
    raise ApiError(error_id, message)
