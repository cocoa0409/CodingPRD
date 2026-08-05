"""Error catalogue (PRD section 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP_STATUS.get(error_id, 400)
        self.message = message or error_id


ERROR_HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_DEFENDANT_NOT_ACTIVE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_CONDITION_NOT_ORDERED": 409,
    "ERR_ASSESSMENT_NOT_APPROVED": 409,
    "ERR_CURFEW_WINDOW_OVERLAP": 409,
    "ERR_SLOT_CAPACITY_EXCEEDED": 409,
    "ERR_PRECONDITION_TIME_NOT_REACHED": 409,
    "ERR_NO_DEVICE_AVAILABLE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_ENUM": 422,
}
