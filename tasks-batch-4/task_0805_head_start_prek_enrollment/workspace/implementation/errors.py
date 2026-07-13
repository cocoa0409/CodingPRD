"""Error definitions for the Head Start & Pre-K Enrollment API."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: id -> http status
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_OWNER": 403,
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_COHORT_NOT_FOUND": 404,
    "ERR_FAMILY_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_OFFER_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_HEALTH_SCREENING_NOT_FOUND": 404,
    "ERR_HOME_VISIT_NOT_FOUND": 404,
    "ERR_TRANSITION_PLAN_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_SUBMITTED": 409,
    "ERR_APPLICATION_NOT_ELIGIBLE": 409,
    "ERR_OFFER_NOT_PENDING": 409,
    "ERR_ENROLLMENT_NOT_ACTIVE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_DUPLICATE_APPLICATION": 409,
    "ERR_AGE_OUT_OF_BAND": 422,
    "ERR_OFFER_EXPIRED": 409,
    "ERR_HOME_VISIT_OVERLAP": 409,
    "ERR_VISIT_DURING_SESSION": 409,
    "ERR_TRANSITION_PREREQ_NOT_MET": 409,
    "ERR_NO_ELIGIBLE_APPLICANTS": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_VALIDATION": 400,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
