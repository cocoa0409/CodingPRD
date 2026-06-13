"""Error catalog and ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status per error id (from PRD §5 / scaffold §1.6)
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_STUDENT_VERSION": 412,
    "ERR_GUARDIAN_CONSENT_REQUIRED": 422,
    "ERR_ROAD_PREREQUISITE_NOT_MET": 422,
    "ERR_RESOURCE_UNAVAILABLE": 422,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_INSTRUCTOR_DOUBLE_BOOKED": 409,
    "ERR_VEHICLE_DOUBLE_BOOKED": 409,
    "ERR_ROAD_HOURS_EXCEEDED": 422,
    "ERR_READINESS_NOT_MET": 422,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE": 409,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)
