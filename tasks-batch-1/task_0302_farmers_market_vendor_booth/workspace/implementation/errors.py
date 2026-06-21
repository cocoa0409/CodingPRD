"""Error catalog (PRD §5) and the APIError exception type."""


class APIError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http status (PRD §5 / scaffold §1.6)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_REFERENTIAL_MISMATCH": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_OUTSIDE_WINDOW": 409,
    "ERR_PERMIT_NOT_VERIFIED": 409,
    "ERR_CATEGORY_NOT_ALLOWED": 409,
    "ERR_BOOTH_OCCUPIED": 409,
    "ERR_TOKEN_OVERDRAW": 409,
    "ERR_STALE_BOOTH_VERSION": 412,
    "ERR_DUPLICATE": 409,
    "ERR_NO_HEALTH_PERMIT": 409,
    "ERR_WAITLIST_NOT_HEAD": 409,
    "ERR_DAY_NOT_OPEN": 409,
    "ERR_VALIDATION_BOUNDS": 422,
    "ERR_SALES_NOT_PRESENT": 409,
}


def err(error_id, message=None):
    return APIError(error_id, ERROR_STATUS[error_id], message)
