"""Error catalog and the ApiError exception type."""


class ApiError(Exception):
    """Carries an error_id, human message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status per error id (from PRD §5 / scaffold §1.6).
ERROR_STATUS = {
    # auth
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_VALIDATION": 400,
    # not found
    "ERR_ARENA_NOT_FOUND": 404,
    "ERR_FIELD_NOT_FOUND": 404,
    "ERR_PACKAGE_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_EQUIPMENT_NOT_FOUND": 404,
    "ERR_RENTAL_NOT_FOUND": 404,
    "ERR_WAIVER_NOT_FOUND": 404,
    "ERR_REFEREE_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_LEAGUE_NOT_FOUND": 404,
    "ERR_MATCH_NOT_FOUND": 404,
    # state
    "ERR_BOOKING_INVALID_STATE": 409,
    "ERR_RENTAL_INVALID_STATE": 409,
    "ERR_WAIVER_INVALID_STATE": 409,
    "ERR_EQUIPMENT_INVALID_STATE": 409,
    "ERR_LEAGUE_INVALID_STATE": 409,
    "ERR_MATCH_INVALID_STATE": 409,
    "ERR_ARENA_CLOSED": 409,
    "ERR_FIELD_CLOSED": 409,
    "ERR_ROUND_NOT_COMPLETE": 409,
    "ERR_ROUND_LIMIT_REACHED": 409,
    "ERR_LEAGUE_NOT_AT_FINAL_ROUND": 409,
    # OCC
    "ERR_STALE_FIELD_VERSION": 412,
    "ERR_STALE_LEAGUE_VERSION": 412,
    # business safety
    "ERR_MINOR_WAIVER_REQUIRED": 422,
    "ERR_REFEREE_REQUIRED": 422,
    # business referential
    "ERR_REFEREE_NOT_ELIGIBLE": 409,
    # business temporal
    "ERR_FIELD_SLOT_CONFLICT": 409,
    "ERR_EQUIPMENT_TIME_CONFLICT": 409,
    "ERR_LEAD_TIME_VIOLATION": 422,
    # business constraint
    "ERR_INVALID_WINDOW": 422,
    "ERR_CAPACITY_EXCEEDED": 409,
    "ERR_EQUIPMENT_UNAVAILABLE": 409,
    "ERR_PACKAGE_INACTIVE": 409,
    # business fiscal
    "ERR_DAMAGE_FEE_EXCEEDS_DEPOSIT": 422,
}


def err(error_id, message=None):
    """Construct an ApiError with the registered HTTP status."""
    return ApiError(error_id, ERROR_STATUS[error_id], message)
