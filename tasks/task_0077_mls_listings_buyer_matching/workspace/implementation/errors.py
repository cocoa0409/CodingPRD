"""Error catalog and ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http_status
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_NOT_LISTING_AGENT": 403,
    "ERR_NOT_BUYER_AGENT": 403,
    "ERR_DUAL_AGENCY_FORBIDDEN": 422,
    "ERR_AGENT_SUSPENDED": 403,
    "ERR_INVALID_STATE": 409,
    "ERR_NOT_YOUR_TURN": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_OVER_BUDGET": 422,
    "ERR_INVALID_AMOUNT": 422,
    "ERR_NO_LOCKBOX": 409,
    "ERR_LOCKBOX_DISABLED": 409,
    "ERR_LOCKBOX_HAS_SHOWINGS": 409,
    "ERR_SHOWING_CONFLICT": 409,
    "ERR_BAD_TIME_WINDOW": 422,
    "ERR_SHOWING_NOT_OVER": 409,
    "ERR_DUPLICATE": 409,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG.get(error_id, 422), message)
