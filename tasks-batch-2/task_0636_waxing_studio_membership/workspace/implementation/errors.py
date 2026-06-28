"""Error catalog (PRD Section 5) and the ApiError exception type."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error ID -> HTTP status (PRD Section 5 Error Code Catalogue)
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_RESOURCE_MISMATCH": 409,
    "ERR_MEMBERSHIP_NOT_ACTIVE": 409,
    "ERR_OUTSIDE_HOURS": 409,
    "ERR_INTRO_NOT_ELIGIBLE": 409,
    "ERR_DEPOSIT_REQUIRED": 409,
    "ERR_TECH_DOUBLE_BOOKED": 409,
    "ERR_ROOM_DOUBLE_BOOKED": 409,
    "ERR_INSUFFICIENT_CREDITS": 409,
    "ERR_OUT_OF_STOCK": 409,
    "ERR_DUPLICATE_EMAIL": 409,
    "ERR_CHECKIN_TOO_EARLY": 409,
    "ERR_VALIDATION_PAGINATION": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
