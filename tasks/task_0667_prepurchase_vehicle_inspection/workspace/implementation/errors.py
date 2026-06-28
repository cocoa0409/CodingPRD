"""Error catalog and the ApiError exception type.

Error IDs and HTTP statuses come verbatim from SCAFFOLD §1.6 / PRD §5.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id -> http_status) — single source of truth.
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_ACCOUNT_SUSPENDED": 409,
    "ERR_INSPECTOR_OFFLINE": 409,
    "ERR_TIER_NOT_CERTIFIED": 409,
    "ERR_WINDOW_OVERLAP": 409,
    "ERR_VEHICLE_DOUBLE_BOOKED": 409,
    "ERR_DAILY_CAP_EXCEEDED": 409,
    "ERR_NO_ACCEPTED_ASSIGNMENT": 409,
    "ERR_EMPTY_REPORT": 409,
    "ERR_CRITICAL_PHOTO_REQUIRED": 409,
    "ERR_REPORT_LOCKED": 409,
    "ERR_PAYMENT_REQUIRED": 409,
    "ERR_INVOICE_NOT_ELIGIBLE": 409,
    "ERR_VIN_REPORT_MISSING": 409,
    "ERR_PAGINATION_INVALID": 422,
}


def err(error_id, message=None):
    """Build an ApiError using the catalog's HTTP status for the given id."""
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
