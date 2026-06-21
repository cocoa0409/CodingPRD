"""Error catalog — exact error_ids and HTTP statuses from PRD §5 / scaffold Table 6."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http_status
ERROR_CATALOG = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_CLIENT_SUSPENDED": 409,
    "ERR_NO_JOBS": 409,
    "ERR_EMPTY_ANALYSIS": 409,
    "ERR_PROJECT_NOT_APPROVED": 409,
    "ERR_PROJECT_NOT_DELIVERED": 409,
    "ERR_PROJECT_HAS_INVOICE": 409,
    "ERR_LINGUIST_INACTIVE": 409,
    "ERR_LINGUIST_NOT_QUALIFIED": 409,
    "ERR_SEGREGATION_VIOLATION": 409,
    "ERR_NO_REVIEWER_ASSIGNED": 409,
    "ERR_NOT_ASSIGNED_TRANSLATOR": 409,
    "ERR_THROUGHPUT_EXCEEDED": 409,
    "ERR_WINDOW_OVERLAP": 409,
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
