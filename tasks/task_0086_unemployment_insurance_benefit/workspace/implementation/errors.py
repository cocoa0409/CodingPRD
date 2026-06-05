"""Error catalog and the ApiError exception.

Error IDs and HTTP statuses come verbatim from PRD §5 / SCAFFOLD §1.6.
"""


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
    "ERR_INVALID_REFERENCE": 422,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_UNTIMELY": 422,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_WORK_SEARCH_INSUFFICIENT": 422,
    "ERR_NOT_ABLE_AVAILABLE": 422,
    "ERR_WAIVER_NOT_ALLOWED": 422,
    "ERR_OVER_RECOVERY": 422,
    "ERR_BALANCE_EXHAUSTED": 422,
    "ERR_REMAND_LIMIT": 422,
    "ERR_EXTENSION_WINDOW": 422,
    "ERR_EXTENSION_ALREADY_APPLIED": 409,
    "ERR_NO_QUALIFYING_WAGES": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_STALE_CLAIM_VERSION": 412,
    "ERR_STALE_OVERPAYMENT_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
