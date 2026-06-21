"""Error catalog and the ApiError exception class.

Every error_id and its HTTP status comes directly from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http_status (PRD §5)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_RESOURCE_OUT_OF_SERVICE": 409,
    "ERR_RENTALS_OUTSTANDING": 409,
    "ERR_LEAGUE_NOT_ACTIVE": 409,
    "ERR_LEAGUE_HAS_SCHEDULED_NIGHTS": 409,
    "ERR_LEAGUE_NO_NIGHTS": 409,
    "ERR_LANE_TIME_CONFLICT": 409,
    "ERR_BAY_TIME_CONFLICT": 409,
    "ERR_CAPACITY_EXCEEDED": 409,
    "ERR_RENTAL_UNAVAILABLE": 409,
    "ERR_CUSTOMER_SUSPENDED": 409,
    "ERR_NOT_WAITLISTED": 409,
    "ERR_DUPLICATE_LANE_NUMBER": 409,
    "ERR_DUPLICATE_NIGHT_INDEX": 409,
    "ERR_PARTY_GUESTS_EXCEED_MAX": 409,
    "ERR_PAGINATION_INVALID": 400,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
