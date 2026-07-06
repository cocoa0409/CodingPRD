"""Error catalog and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http status
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_PARK_CLOSED": 409,
    "ERR_WAIVER_MISSING": 409,
    "ERR_GUARDIAN_REQUIRED": 422,
    "ERR_HEIGHT_BELOW_MIN": 422,
    "ERR_LANE_TURN_OVERLAP": 409,
    "ERR_BLOCK_WINDOW_CLOSED": 409,
    "ERR_LANE_UNAVAILABLE": 409,
    "ERR_PASS_DAILY_LIMIT": 409,
    "ERR_PASS_NOT_VALID": 409,
    "ERR_CAPACITY_EXCEEDED": 409,
    "ERR_INVALID_REQUEST": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
