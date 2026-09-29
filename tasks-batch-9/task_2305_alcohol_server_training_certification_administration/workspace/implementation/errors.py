"""Error catalogue (PRD section 5 / SCAFFOLD 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- catalogue: error_id -> http status ------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CATALOG_NOT_FOUND": 404,
    "ERR_TRAINING_NOT_FOUND": 404,
    "ERR_CREDENTIAL_NOT_FOUND": 404,
    "ERR_EMPLOYER_NOT_FOUND": 404,
    "ERR_STALE_SESSION_VERSION": 412,
    "ERR_STALE_COURSE_VERSION": 412,
    "ERR_STALE_ACCOUNT_VERSION": 412,
    "ERR_COURSE_INVALID_STATE": 409,
    "ERR_APPROVAL_INVALID_STATE": 409,
    "ERR_TRAINER_INVALID_STATE": 409,
    "ERR_SESSION_INVALID_STATE": 409,
    "ERR_ENROLLMENT_INVALID_STATE": 409,
    "ERR_CERTIFICATE_INVALID_STATE": 409,
    "ERR_SUBMISSION_INVALID_STATE": 409,
    "ERR_ACCOUNT_INVALID_STATE": 409,
    "ERR_APPROVAL_NOT_EFFECTIVE": 422,
    "ERR_APPROVAL_STALE_CONTENT": 409,
    "ERR_TRAINER_NOT_CERTIFIED": 422,
    "ERR_PROCTOR_SEPARATION_REQUIRED": 422,
    "ERR_SERVER_WORK_RESTRICTED": 422,
    "ERR_MANDATE_TRACK_MISMATCH": 422,
    "ERR_IDENTITY_ALREADY_REGISTERED": 409,
    "ERR_DUPLICATE_APPROVAL_REQUEST": 409,
    "ERR_DUPLICATE_ENROLLMENT": 409,
    "ERR_DUPLICATE_ASSIGNMENT": 409,
    "ERR_SESSION_AT_CAPACITY": 409,
    "ERR_EMPTY_ROSTER": 422,
    "ERR_ATTENDANCE_INCOMPLETE": 422,
    "ERR_RETAKE_LIMIT_EXCEEDED": 422,
    "ERR_TRAINER_SCHEDULE_CONFLICT": 409,
    "ERR_SERVER_SESSION_OVERLAP": 409,
    "ERR_RETAKE_COOLING_OFF": 422,
    "ERR_EXAM_WINDOW_NOT_OPEN": 422,
    "ERR_SESSION_WINDOW_IN_PAST": 422,
    "ERR_INSUFFICIENT_SEAT_CREDITS": 402,
    "ERR_COMPLIANCE_RATE_TOO_LOW": 422,
}


def fail(error_id, message=None):
    """Raise the catalogued error."""
    raise ApiError(error_id, ERROR_STATUS[error_id], message)


def invalid(message="Malformed request."):
    fail("ERR_INVALID_REQUEST", message)
