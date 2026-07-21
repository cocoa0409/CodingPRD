"""Error type + catalog. Error IDs and HTTP statuses come straight from the
scaffold §1.6 error catalogue / PRD Section 5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status per error id (single source of truth).
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_ITEM_NOT_AVAILABLE": 409,
    "ERR_ALLOCATION_NOT_READY": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_RENTAL_OVERLAP": 409,
    "ERR_STATION_DOUBLE_BOOKED": 409,
    "ERR_REGISTRATION_CLOSED": 409,
    "ERR_TOURNAMENT_FULL": 409,
    "ERR_ALREADY_REGISTERED": 409,
    "ERR_ONE_ACTIVE_PREORDER": 409,
    "ERR_INSUFFICIENT_STORE_CREDIT": 402,
    "ERR_INSUFFICIENT_PAYMENT": 402,
    "ERR_PAGINATION_INVALID": 400,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)
