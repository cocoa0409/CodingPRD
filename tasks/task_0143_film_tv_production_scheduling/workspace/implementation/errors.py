"""Error catalogue and the ApiError exception type.

Every error_id / http_status pair is taken verbatim from PRD section 5 and the
SCAFFOLD errors table.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue: error_id -> http_status
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_CROSS_PRODUCTION_REFERENCE": 409,
    "ERR_DUPLICATE_DAY_NUMBER": 409,
    "ERR_DOUBLE_BOOKED": 409,
    "ERR_PERMIT_WINDOW_CONFLICT": 409,
    "ERR_CREW_TIME_CONFLICT": 409,
    "ERR_INVALID_TIME_RANGE": 422,
    "ERR_DUPLICATE_FRINGE": 409,
    "ERR_BUDGET_WOULD_EXCEED": 409,
    "ERR_SCENE_SCHEDULE_LOCKED": 409,
    "ERR_VALIDATION_FAILED": 422,
    "ERR_PAGINATION_INVALID": 400,
    "ERR_DAILIES_FLAG_REASON_REQUIRED": 422,
    "ERR_PRODUCTION_NOT_ACTIVE": 409,
    "ERR_OPEN_ASSIGNMENTS_BLOCK_WRAP": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
