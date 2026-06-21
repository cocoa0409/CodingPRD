"""Error catalogue and the ApiError exception class."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id -> http status, from PRD §5 / scaffold §1.6
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_INVENTORY": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_SLOT_VERSION": 412,
    "ERR_STALE_INVENTORY_VERSION": 412,
    "ERR_SLOT_CUTOFF_PASSED": 409,
    "ERR_HOLD_NOT_EXPIRABLE": 409,
    "ERR_SLOT_STORE_MISMATCH": 409,
    "ERR_SUBSTITUTION_GROUP_MISMATCH": 409,
    "ERR_ORDER_NOT_VERIFIED": 409,
    "ERR_OVER_HANDOVER": 409,
    "ERR_CURBSIDE_FULL": 409,
    "ERR_DUPLICATE_CHECKIN": 409,
    "ERR_SLOT_FULL": 409,
    "ERR_INSUFFICIENT_AVAILABILITY": 409,
    "ERR_CUSTOMER_BLOCKED": 409,
    "ERR_INSUFFICIENT_ON_HAND": 409,
    "ERR_STAGE_NOT_READY": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
