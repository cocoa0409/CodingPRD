class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http_status
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_REFERENCE": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_COHORT_VERSION": 412,
    "ERR_PRICING_INCOMPLETE": 422,
    "ERR_PROGRAM_RETIRED": 409,
    "ERR_VERSION_NOT_APPROVED": 409,
    "ERR_FACILITATOR_NOT_CERTIFIED": 409,
    "ERR_DELIVERY_MODE_MISMATCH": 409,
    "ERR_ENROLL_WINDOW_CLOSED": 409,
    "ERR_BEFORE_START": 409,
    "ERR_BEFORE_END": 409,
    "ERR_COHORT_FULL": 409,
    "ERR_WAITLIST_FULL": 409,
    "ERR_DUPLICATE_REGISTRATION": 409,
    "ERR_COHORT_NOT_OPEN": 409,
    "ERR_COHORT_NOT_RUNNING": 409,
    "ERR_MIN_SEATS_NOT_MET": 409,
    "ERR_SESSION_OUT_OF_RANGE": 422,
    "ERR_ROOM_CONFLICT": 409,
    "ERR_FACILITATOR_DOUBLE_BOOKED": 409,
    "ERR_NOT_ELIGIBLE_FOR_CERTIFICATE": 409,
    "ERR_CERTIFICATE_STILL_VALID": 409,
    "ERR_CONTRACT_BUDGET_EXCEEDED": 409,
    "ERR_CONTRACT_HAS_OPEN_COHORTS": 409,
    "ERR_EVALUATION_NOT_ALLOWED": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG.get(error_id, 400), message)
