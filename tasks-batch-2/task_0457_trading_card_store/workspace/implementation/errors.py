"""Error classes and the error catalog (PRD §5)."""


class ApiError(Exception):
    """An error carrying an error_id, human message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# PRD §5 Error Code Catalogue: error_id -> HTTP status.
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_QUANTITY": 422,
    "ERR_INVALID_GRADE": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_CUSTOMER_BANNED": 409,
    "ERR_INVALID_EVENT_CAPACITY": 422,
    "ERR_NO_SEATED_PLAYERS": 409,
    "ERR_ROUND_NOT_COMPLETE": 409,
    "ERR_MAX_ROUNDS_REACHED": 409,
    "ERR_EVENT_FULL": 409,
    "ERR_SCHEDULE_CONFLICT": 409,
    "ERR_VENUE_OVERLAP": 409,
    "ERR_EMPTY_BUYLIST": 422,
    "ERR_INVENTORY_RESERVED": 409,
    "ERR_ALLOCATION_EXCEEDED": 409,
    "ERR_RELEASE_NOT_LIVE": 409,
    "ERR_REGISTRATION_NOT_PAID": 409,
    "ERR_INSUFFICIENT_STORE_CREDIT": 402,
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    """Build an ApiError using the catalog status for error_id."""
    return ApiError(error_id, ERROR_STATUS[error_id], message)
