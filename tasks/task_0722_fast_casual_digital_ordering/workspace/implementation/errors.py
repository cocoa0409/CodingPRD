"""Error catalog and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


# Error ID -> HTTP status (from PRD §5 / scaffold §1.6)
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_MODIFIER_MISMATCH": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_ALLERGEN_BLOCKED": 422,
    "ERR_SLOT_UNAVAILABLE": 422,
    "ERR_SLOT_CAPACITY_EXCEEDED": 409,
    "ERR_NO_LOCKER_AVAILABLE": 409,
    "ERR_INSUFFICIENT_POINTS": 422,
    "ERR_REFUND_EXCEEDS_CHARGE": 422,
    "ERR_STALE_SLOT_VERSION": 412,
    "ERR_EMPTY_ORDER": 422,
    "ERR_ITEM_UNAVAILABLE": 422,
    "ERR_PAYMENT_FAILED": 402,
    "ERR_DUPLICATE_EMAIL": 409,
    "ERR_INVALID_QUANTITY": 422,
    "ERR_CHALLENGE_NOT_READY": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
