"""Error catalog and ApiError exception (PRD section 5)."""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_PRODUCT_RECALLED": 409,
    "ERR_REGISTRATION_NOT_ACTIVE": 409,
    "ERR_WARRANTY_EXPIRED": 409,
    "ERR_OFFER_EXPIRED": 409,
    "ERR_NO_REPAIR_LINES": 422,
    "ERR_SCHEDULE_CONFLICT": 409,
    "ERR_DUPLICATE": 409,
    "ERR_ORDER_NOT_CAPTURED": 409,
    "ERR_MONOGRAM_PENDING": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_REQUEST": 422,
    "ERR_OPEN_SPECIAL_ORDER": 409,
    "ERR_CLAIM_OPEN_ON_REGISTRATION": 409,
    "ERR_VALIDATION_RANGE": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or error_id
        super().__init__(self.message)


def err(error_id, message=None):
    return ApiError(error_id, message)
