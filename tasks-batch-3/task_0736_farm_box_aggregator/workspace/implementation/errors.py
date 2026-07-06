"""Error catalog and ApiError exception.

Every error_id and its HTTP status is read verbatim from the PRD error
catalogue (PRD section 5) / SCAFFOLD 1.6. Nothing here is assumed.
"""

# error_id -> HTTP status code (PRD section 5 Error Code Catalogue)
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_PAGINATION": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_CYCLE_NOT_OPEN": 409,
    "ERR_EMPTY_ORDER": 409,
    "ERR_ORDER_NOT_ALLOCATED": 409,
    "ERR_LINES_NOT_PACKED": 409,
    "ERR_ORDER_IN_PACKOUT": 409,
    "ERR_CYCLE_HAS_OPEN_ORDERS": 409,
    "ERR_PRODUCT_FARM_MISMATCH": 409,
    "ERR_OFFERING_CYCLE_MISMATCH": 409,
    "ERR_NOT_LINE_OWNER": 403,
    "ERR_FARM_NOT_SNAP_AUTHORIZED": 422,
    "ERR_CYCLE_WINDOW_CONFLICT": 409,
    "ERR_SLOT_CAPACITY_EXCEEDED": 409,
    "ERR_OVER_PACK": 409,
    "ERR_INVALID_WEIGHT": 422,
    "ERR_INSUFFICIENT_AVAILABILITY": 409,
    "ERR_STALE_FARM_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_HTTP[error_id]
        self.message = message or error_id
        super().__init__(self.message)
