"""Error catalogue (PRD Section 5 / SCAFFOLD §1.6).

Each ApiError carries an error_id, a human-readable message, and an HTTP status.
The error response body uses the exact field names from the response envelope:
data.error_id and data.message.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status for each error_id (PRD Section 5 Error Code Catalogue).
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_PROJECT_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_VARIANT_PRODUCT_MISMATCH": 422,
    "ERR_PRODUCT_RETIRED": 422,
    "ERR_DESIGN_ALREADY_ACCEPTED": 409,
    "ERR_CREW_NOT_CERTIFIED": 422,
    "ERR_CREW_CAPACITY_EXCEEDED": 422,
    "ERR_CREW_DOUBLE_BOOKED": 409,
    "ERR_INVALID_WINDOW": 422,
    "ERR_SCOPE_NOT_FINALIZED": 409,
    "ERR_DEPOSIT_INSUFFICIENT": 422,
    "ERR_BALANCE_NOT_DUE": 409,
    "ERR_PROJECT_NOT_CLOSEABLE": 409,
    "ERR_VALIDATION_PAGINATION": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)
