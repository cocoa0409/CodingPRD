"""Error catalogue. Error IDs and HTTP statuses taken verbatim from PRD §5 and
SCAFFOLD errors table."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status by error id (PRD §5 Error Code Catalogue)
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_PROGRAM_SUSPENDED": 409,
    "ERR_PARTICIPANT_NOT_ENROLLED": 409,
    "ERR_LOC_NOT_CERTIFIED": 409,
    "ERR_LOC_BELOW_THRESHOLD": 409,
    "ERR_NO_ACTIVE_CARE_PLAN": 409,
    "ERR_IDT_INCOMPLETE": 409,
    "ERR_CARE_PLAN_NO_GOALS": 409,
    "ERR_CARE_PLAN_NOT_ACTIVE": 409,
    "ERR_CANNOT_VOID_ACTIVE": 409,
    "ERR_WITHDRAW_NOT_ALLOWED": 409,
    "ERR_INVOLUNTARY_CANNOT_DENY": 409,
    "ERR_NOT_FIRST_OF_MONTH": 422,
    "ERR_AGE_INELIGIBLE": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_TRANSPORT_OVERLAP": 409,
    "ERR_DUPLICATE_PERIOD": 409,
    "ERR_CENSUS_FULL": 409,
    "ERR_CAPACITY_EXCEEDED": 409,
    "ERR_NO_COVERAGE_FOR_MONTH": 409,
    "ERR_RECOUP_EXCEEDS_BILLED": 422,
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
