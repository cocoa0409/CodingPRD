"""Error catalogue (PRD §5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue — id -> http status (PRD §5 / SCAFFOLD 1.6)
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_TIME_RANGE": 422,
    "ERR_LANE_TIME_CONFLICT": 409,
    "ERR_ANALYZER_CAPACITY": 409,
    "ERR_CLASS_PROFILE_MISSING": 409,
    "ERR_OBD_NOT_APPLICABLE": 409,
    "ERR_INSPECTION_INCOMPLETE": 409,
    "ERR_RECORD_NOT_PASSED": 409,
    "ERR_CERTIFICATE_EXISTS": 409,
    "ERR_REPAIR_LIMIT_NOT_MET": 409,
    "ERR_REINSPECTION_LIMIT": 409,
    "ERR_LINE_NOT_ELIGIBLE": 409,
    "ERR_EMPTY_BATCH": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
