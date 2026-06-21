"""Error classes and error-id constants for the VMS API."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalogue (id -> http status) ---
ERROR_CATALOG = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_PROGRAM_NOT_ACTIVE": 409,
    "ERR_SUPPLIER_NOT_ELIGIBLE": 409,
    "ERR_DISTRIBUTION_NOT_RELEASED": 409,
    "ERR_PAY_RATE_EXCEEDS_MAX": 409,
    "ERR_MARKUP_EXCEEDS_MAX": 409,
    "ERR_NEGOTIATION_ROUNDS_EXCEEDED": 409,
    "ERR_REQUISITION_FULL": 409,
    "ERR_REQUISITION_HAS_HIRES": 409,
    "ERR_TENURE_LIMIT_REACHED": 409,
    "ERR_MILESTONE_SEQUENCE_VIOLATION": 409,
    "ERR_SOW_VALUE_EXCEEDED": 409,
    "ERR_SOW_NO_MILESTONES": 409,
    "ERR_OPEN_APPROVALS_PENDING": 409,
    "ERR_ASSIGNMENT_NOT_ACTIVE": 409,
    "ERR_EMPTY_TIMESHEET": 409,
    "ERR_DUPLICATE_WEEK": 409,
    "ERR_WORKER_DOUBLE_BOOKED": 409,
    "ERR_DUPLICATE_WORKER": 409,
    "ERR_DUPLICATE_SUBMITTAL": 409,
    "ERR_VALIDATION_LIMIT": 400,
    "ERR_TIER_INVALID": 400,
    "ERR_THRESHOLD_INVALID": 400,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
