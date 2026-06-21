"""Error catalog and custom exception type.

Error IDs and HTTP statuses are taken verbatim from SCAFFOLD §1.6 / PRD §5.
"""


class ApiError(Exception):
    """An error carrying the scaffold's error_id, message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status per error_id (PRD §5 / scaffold §1.6).
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_RESOURCE_TYPE_MISMATCH": 422,
    "ERR_CLIENT_NOT_BOOKABLE": 422,
    "ERR_BOOKING_IN_PAST": 422,
    "ERR_RESOURCE_INACTIVE": 422,
    "ERR_STYLIST_DOUBLE_BOOKED": 409,
    "ERR_RESOURCE_DOUBLE_BOOKED": 409,
    "ERR_PACKAGE_EXHAUSTED": 422,
    "ERR_INSUFFICIENT_STOCK": 422,
    "ERR_ALREADY_CHECKED_OUT": 409,
    "ERR_STALE_STYLIST_VERSION": 412,
    "ERR_STALE_SALON_VERSION": 412,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DISPUTE_TARGET_INVALID": 422,
}


def err(error_id, message=None):
    """Construct an ApiError using the catalog's HTTP status for error_id."""
    return ApiError(error_id, ERROR_STATUS[error_id], message)
