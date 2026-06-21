"""Error catalog (PRD §5) and the ApiError exception.

Every error_id and HTTP status is taken verbatim from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id -> http_status) from PRD §5.
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_BOOKING_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CROSS_INN_REFERENCE": 409,
    "ERR_INVALID_DATE_RANGE": 422,
    "ERR_OCCUPANCY_EXCEEDED": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_RESOURCE_RETIRED": 409,
    "ERR_BREAKFAST_OVER_PARTY": 422,
    "ERR_ROOM_DOUBLE_BOOKED": 409,
    "ERR_TURNOVER_NOT_READY": 409,
    "ERR_MIN_NIGHTS_NOT_MET": 422,
    "ERR_PAYMENT_EXCEEDS_BALANCE": 422,
    "ERR_GIFT_INSUFFICIENT": 422,
    "ERR_DEPOSIT_NOT_MET": 422,
    "ERR_ALREADY_REMITTED": 409,
    "ERR_STALE_ROOM_VERSION": 412,
    "ERR_STALE_GIFT_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
