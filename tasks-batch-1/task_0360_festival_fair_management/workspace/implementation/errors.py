"""Error catalog and the ApiError exception type.

Every error_id and HTTP status here is taken verbatim from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> http status
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 422,
    "ERR_INVALID_REQUEST": 422,
    "ERR_DAYCOUNT_RANGE": 422,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_FESTIVAL_POSTURE": 409,
    "ERR_FESTIVAL_SUSPENDED": 409,
    "ERR_ALREADY_INSIDE": 409,
    "ERR_REENTRY_LIMIT": 409,
    "ERR_STAGE_CONFLICT": 409,
    "ERR_ARTIST_DOUBLE_BOOKED": 409,
    "ERR_DUPLICATE_RFID": 409,
    "ERR_ZONE_FULL": 409,
    "ERR_CAPACITY_FULL": 409,
    "ERR_FEE_UNPAID": 409,
    "ERR_INSUFFICIENT_BALANCE": 422,
    "ERR_STALE_ZONE_VERSION": 412,
    "ERR_STALE_LOT_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
