"""Error catalog and the ApiError exception type.

Every error_id and HTTP status is taken verbatim from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http status.
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_EMPTY_CREDENTIALS": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_PRIOR_AUTH_REQUIRED": 402,
    "ERR_INSUFFICIENT_AUTH_UNITS": 422,
    "ERR_SCREENING_NOT_CLEARED": 409,
    "ERR_CENTER_QUALITY_HOLD": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_CRITICAL_RESULT_REQUIRED": 409,
    "ERR_RADIOLOGIST_NOT_CREDENTIALED": 422,
    "ERR_TECH_NOT_CREDENTIALED": 422,
    "ERR_ROOM_MODALITY_MISMATCH": 422,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_ROOM_DOUBLE_BOOKED": 409,
    "ERR_TECH_DOUBLE_BOOKED": 409,
    "ERR_NO_ACCEPTED_SERIES": 409,
    "ERR_SERIES_STILL_CAPTURING": 409,
    "ERR_REJECT_REASON_REQUIRED": 422,
    "ERR_ALREADY_CLAIMED": 409,
    "ERR_NOT_ASSIGNED_TECH": 403,
    "ERR_NOT_ASSIGNED_RADIOLOGIST": 403,
    "ERR_TOO_EARLY_TO_CHECK_IN": 409,
    "ERR_REPORT_NOT_FINAL": 409,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
