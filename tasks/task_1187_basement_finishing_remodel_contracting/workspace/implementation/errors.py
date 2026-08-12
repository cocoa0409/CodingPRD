"""Error types and the error catalog (SCAFFOLD §1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error catalog: id -> http status
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCED_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_PROJECT_STATE_FORBIDS": 409,
    "ERR_MOISTURE_NOT_CLEARED": 409,
    "ERR_DESIGN_REVISION_STALE": 409,
    "ERR_EGRESS_NONCOMPLIANT": 422,
    "ERR_CEILING_NONCOMPLIANT": 422,
    "ERR_ASSESSMENT_IN_PROGRESS": 409,
    "ERR_REASSESSMENT_NOT_ALLOWED": 409,
    "ERR_PHASE_CYCLE": 422,
    "ERR_ZONE_SCHEDULE_OVERLAP": 409,
    "ERR_CREW_CAPACITY_EXCEEDED": 409,
    "ERR_FUTURE_WORK_DATE": 422,
    "ERR_PERMIT_EXPIRED": 409,
    "ERR_WARRANTY_EXPIRED": 409,
    "ERR_PHASES_INCOMPLETE": 409,
    "ERR_ROUGH_IN_REQUIRED": 409,
    "ERR_ALLOWANCE_OVERDRAW": 422,
    "ERR_INVALID_CLAIM_AMOUNT": 422,
}


def fail(error_id, message):
    raise ApiError(error_id, message, ERRORS[error_id])
