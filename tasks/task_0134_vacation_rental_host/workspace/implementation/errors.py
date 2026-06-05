"""Error catalogue and the ApiError exception (PRD §5, SCAFFOLD §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> http_status (PRD §5 Error Code Catalogue)
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_LISTING_NOT_BOOKABLE": 409,
    "ERR_SCREENING_NOT_PASSED": 409,
    "ERR_INVALID_DATE_RANGE": 422,
    "ERR_MIN_NIGHTS": 422,
    "ERR_DATES_UNAVAILABLE": 409,
    "ERR_RATE_PLAN_OVERLAP": 409,
    "ERR_INVALID_CLAIM_AMOUNT": 422,
    "ERR_PAYOUT_NOT_DUE": 409,
    "ERR_CLAIM_BLOCKS_PAYOUT": 409,
    "ERR_STALE_CALENDAR_VERSION": 412,
    "ERR_RELEASE_BOOKING_BLOCK": 409,
    "ERR_VALIDATION": 422,
    "ERR_DUPLICATE_EXTERNAL_REF": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
