"""Error catalogue and the ApiError exception type.

Error IDs and HTTP statuses are taken verbatim from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error ID -> HTTP status (PRD §5 Error Code Catalogue)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_CAPACITY_MISMATCH": 422,
    "ERR_ZONE_MISMATCH": 422,
    "ERR_INSUFFICIENT_SALT": 422,
    "ERR_WINDOW_OVERLAP": 409,
    "ERR_SERVICE_GAP_VIOLATION": 409,
    "ERR_ROUTE_FULL": 409,
    "ERR_RENTAL_NOT_ALLOWED": 422,
    "ERR_SUPERSEDE_NOT_VOID": 422,
    "ERR_INVOICE_CLOSED": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
