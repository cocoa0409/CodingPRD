"""Error catalogue (§5 / §1.6) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id -> default HTTP status (from PRD §5 catalogue).
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_MEMBER_RESTRICTED": 403,
    "ERR_INTRO_ALREADY_USED": 409,
    "ERR_INSTRUCTOR_CONFLICT": 409,
    "ERR_ROOM_CONFLICT": 409,
    "ERR_CAPACITY_EXCEEDS_ROOM": 409,
    "ERR_MEMBERSHIP_INACTIVE": 409,
    "ERR_DUPLICATE_RESERVATION": 409,
    "ERR_WAITLIST_FULL": 409,
    "ERR_INSUFFICIENT_CREDITS": 402,
    "ERR_FREEZE_NOT_ALLOWED": 409,
    "ERR_STUDIO_CLOSED": 409,
    "ERR_SESSION_NOT_BOOKABLE": 409,
    "ERR_INVALID_CANCEL_WINDOW": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
