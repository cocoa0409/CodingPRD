"""Error classes and error-ID constants for the Test-Prep Tutoring API.

Every error_id and its HTTP status comes verbatim from PRD §5 / scaffold §1.6.
"""


class ApiError(Exception):
    """An application error carrying error_id, HTTP status, and a message."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id -> http_status) catalog, verbatim from PRD §5.
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_COUPON": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_COURSE_NOT_PUBLISHED": 409,
    "ERR_INSTRUCTOR_NOT_CERTIFIED": 409,
    "ERR_INSTRUCTOR_TIME_CONFLICT": 409,
    "ERR_INSTRUCTOR_OVERLOADED": 409,
    "ERR_COHORT_WINDOW_NOT_OPEN": 409,
    "ERR_COHORT_NOT_ENROLLABLE": 409,
    "ERR_COHORT_FULL": 409,
    "ERR_DUPLICATE_ENROLLMENT": 409,
    "ERR_STUDENT_SCHEDULE_CONFLICT": 409,
    "ERR_PAYMENT_NOT_SETTLED": 409,
    "ERR_ENROLLMENT_NOT_SCORABLE": 409,
    "ERR_SCORE_OUT_OF_RANGE": 422,
    "ERR_MATERIALS_EXPIRED": 403,
    "ERR_GUARANTEE_NOT_ELIGIBLE": 409,
    "ERR_GUARANTEE_THRESHOLD_MET": 409,
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    """Construct an ApiError using the catalog HTTP status for error_id."""
    return ApiError(error_id, ERROR_STATUS[error_id], message)
