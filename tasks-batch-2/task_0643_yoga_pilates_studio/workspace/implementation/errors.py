"""Error classes and the error catalog (id -> http status)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http status code (PRD §5 / scaffold §1.6)
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_MEMBER_SUSPENDED": 409,
    "ERR_ENTITLEMENT_NOT_USABLE": 409,
    "ERR_NO_CREDITS_REMAINING": 409,
    "ERR_INTRO_NOT_ELIGIBLE": 409,
    "ERR_TEACHER_NOT_CERTIFIED": 409,
    "ERR_ROOM_DOUBLE_BOOKED": 409,
    "ERR_TEACHER_DOUBLE_BOOKED": 409,
    "ERR_CAPACITY_EXCEEDS_ROOM": 422,
    "ERR_WAITLIST_FULL": 409,
    "ERR_SESSION_NOT_BOOKABLE": 409,
    "ERR_FREEZE_LIMIT_REACHED": 409,
    "ERR_ROOM_CLOSED": 409,
    "ERR_ENTITLEMENT_FROZEN": 409,
    "ERR_END_BEFORE_START": 422,
    "ERR_FEE_ALREADY_RESOLVED": 409,
    "ERR_VERSION_REQUIRED": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG.get(error_id, 400), message)
