"""Error catalogue (PRD 5) and the ApiError exception carrying error_id + status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue: error_id -> HTTP status (PRD 5 / scaffold 1.6)
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_PRECONDITION_NOT_MET": 409,
    "ERR_HOLD_EXPIRED": 409,
    "ERR_CONNECTION_TOO_TIGHT": 409,
    "ERR_SEAT_TAKEN": 409,
    "ERR_SOLD_OUT": 409,
    "ERR_REFUND_NOT_ALLOWED": 409,
    "ERR_PASS_DEPLETED": 409,
    "ERR_PASS_EXPIRED": 409,
    "ERR_ACCESSIBILITY_UNAVAILABLE": 409,
    "ERR_FARE_CLASS_RETIRED": 409,
    "ERR_ROUTE_NOT_PUBLISHED": 409,
    "ERR_NOT_PAID": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_DUPLICATE_EMAIL": 409,
    "ERR_VALIDATION_PAGINATION": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
