"""Error catalog and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (id -> http status) per PRD §5 / scaffold §1.6.
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_OWNERSHIP": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_CLEANER_NOT_CLEARED": 409,
    "ERR_RECLEAN_NOT_ELIGIBLE": 409,
    "ERR_RECLEAN_WINDOW_CLOSED": 409,
    "ERR_ADDON_NOT_ALLOWED": 422,
    "ERR_ADDRESS_ARCHIVED": 409,
    "ERR_NO_CLEANER_AVAILABLE": 409,
    "ERR_CLEANER_DOUBLE_BOOKED": 409,
    "ERR_ADDRESS_DOUBLE_BOOKED": 409,
    "ERR_TIP_NOT_ALLOWED": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_REQUEST": 422,
}


def err(error_id, message=None):
    """Construct an ApiError using the cataloged HTTP status for error_id."""
    return ApiError(error_id, ERRORS.get(error_id, 400), message)
