"""Error catalog and the ApiError exception type."""


class ApiError(Exception):
    """A domain error carrying the scaffold error_id, HTTP status, and message."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# §1.6 Error Code Catalog — (error_id -> http_status)
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_SESSION_VERSION": 412,
    "ERR_STALE_GIFT_CARD_VERSION": 412,
    "ERR_INSTRUCTOR_SKILL_INSUFFICIENT": 422,
    "ERR_MEMBER_BLOCKED": 403,
    "ERR_SUBSTITUTION_NOT_APPLICABLE": 422,
    "ERR_GIFT_CARD_NOT_OWNED": 403,
    "ERR_PRIVATE_REQUIRES_FULL_BUYOUT": 422,
    "ERR_INSUFFICIENT_SEATS": 409,
    "ERR_STATION_DOUBLE_BOOKED": 409,
    "ERR_INVALID_TIME_WINDOW": 422,
    "ERR_WAITLIST_NOT_ALLOWED": 409,
    "ERR_INVALID_RELOAD_AMOUNT": 422,
    "ERR_INVALID_WALLET_ADJUSTMENT": 422,
}


def err(error_id, message=None):
    """Build an ApiError using the catalog's HTTP status for error_id."""
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
