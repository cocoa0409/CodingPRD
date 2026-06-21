"""Error catalogue and the ApiError exception type."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue (id -> http status) from PRD §5 / scaffold §1.6.
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_AUTH_NOT_VERIFIED": 409,
    "ERR_PICKUP_CODE_MISMATCH": 409,
    "ERR_MAILBOX_OCCUPIED": 409,
    "ERR_NO_LOCKER_AVAILABLE": 409,
    "ERR_UNRESOLVED_PACKAGES": 409,
    "ERR_AGREEMENT_NOT_ACTIVE": 409,
    "ERR_DUPLICATE": 409,
    "ERR_NO_RECIPIENTS": 409,
    "ERR_INVALID_CLOCK": 422,
    "ERR_PAYMENT_EXCEEDS_BALANCE": 409,
    "ERR_MAILBOX_NOT_VACANT": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
