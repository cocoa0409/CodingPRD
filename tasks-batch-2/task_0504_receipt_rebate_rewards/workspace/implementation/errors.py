"""Error catalogue (PRD §5 / SCAFFOLD errors table). Each ApiError carries the
machine-readable error_id, an HTTP status, and a human-readable message."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error-id -> http status, straight from the catalogue.
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 422,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_OFFER_INACTIVE": 409,
    "ERR_DOUBLE_DIP_BLOCKED": 409,
    "ERR_ATTRIBUTION_WINDOW_EXPIRED": 409,
    "ERR_MEMBER_SUSPENDED": 409,
    "ERR_MEMBER_NOT_VERIFIED": 409,
    "ERR_MIN_SPEND_NOT_MET": 409,
    "ERR_BELOW_CASHOUT_MINIMUM": 422,
    "ERR_INSUFFICIENT_BALANCE": 422,
    "ERR_MERCHANT_DISABLED": 409,
    "ERR_CLAIM_ALREADY_TERMINAL": 409,
    "ERR_RETURN_EXCEEDS_PURCHASE": 422,
    "ERR_REFERRAL_NOT_QUALIFIED": 409,
    "ERR_DUPLICATE_REFERRAL": 409,
    "ERR_VALIDATION_PAGINATION": 400,
    "ERR_CASHOUT_NOT_RESERVABLE": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
