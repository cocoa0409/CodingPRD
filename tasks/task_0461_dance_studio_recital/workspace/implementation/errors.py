"""Error catalogue (PRD section 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> http status (PRD section 5)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_LEVEL_TOO_LOW": 422,
    "ERR_AGE_OUT_OF_BAND": 422,
    "ERR_ROOM_CONFLICT": 409,
    "ERR_INSTRUCTOR_CONFLICT": 409,
    "ERR_INSTRUCTOR_OVERLOADED": 422,
    "ERR_ROSTER_FULL": 422,
    "ERR_MAKEUP_INELIGIBLE": 422,
    "ERR_RECITAL_SOLD_OUT": 409,
    "ERR_FAMILY_DELINQUENT": 402,
    "ERR_NO_PAYMENT_METHOD": 402,
    "ERR_NOT_ENROLLED_IN_SECTION": 422,
    "ERR_INSUFFICIENT_CHAPERONES": 422,
    "ERR_DUPLICATE_INVOICE": 409,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CAPACITY_EXCEEDED": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
