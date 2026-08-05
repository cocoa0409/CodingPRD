"""Error class and error-id constants for the Vacation Rental Management API."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Catalogue (error_id -> http status)
ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_PROPERTY_NOT_BOOKABLE": 409,
    "ERR_SCREENING_NOT_APPROVED": 409,
    "ERR_TURNOVER_NOT_READY": 409,
    "ERR_TURNOVER_NOT_CLEANED": 409,
    "ERR_STATEMENT_NOT_FINALIZED": 409,
    "ERR_PERMIT_NOT_ACTIVE": 409,
    "ERR_BOOKING_NOT_CHECKED_OUT": 409,
    "ERR_GUEST_BANNED": 403,
    "ERR_SOD_INSPECTOR_IS_CLEANER": 409,
    "ERR_PERMIT_EXPIRED": 409,
    "ERR_OPEN_WORK_ORDERS": 409,
    "ERR_OWNER_APPROVAL_REQUIRED": 403,
    "ERR_VENDOR_NOT_CLEANER": 422,
    "ERR_MIN_STAY_NOT_MET": 422,
    "ERR_DATES_UNAVAILABLE": 409,
    "ERR_VENDOR_UNAVAILABLE": 409,
    "ERR_NEGATIVE_PAYOUT": 409,
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERR[error_id], message)
