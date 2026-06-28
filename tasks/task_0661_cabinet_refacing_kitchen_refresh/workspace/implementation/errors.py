"""Error catalog (§1.6 / PRD §5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id -> http status (PRD §5 catalogue)
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_PROJECT_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_MEASURE_PROJECT_MISMATCH": 422,
    "ERR_MEASURE_NOT_COMPLETED": 409,
    "ERR_QUOTE_EXPIRED": 409,
    "ERR_QUOTE_NOT_APPROVED": 409,
    "ERR_STALE_QUOTE_VERSION": 412,
    "ERR_LEAD_TIME_NOT_ELAPSED": 409,
    "ERR_CREW_NOT_CERTIFIED": 422,
    "ERR_WINDOW_BEFORE_READY": 409,
    "ERR_CREW_WINDOW_CONFLICT": 409,
    "ERR_CREW_DAY_FULL": 409,
    "ERR_INVALID_WINDOW": 422,
    "ERR_OUT_OF_WARRANTY": 409,
    "ERR_DTI_EXCEEDED": 422,
    "ERR_WARRANTY_NOT_COVERED": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)
