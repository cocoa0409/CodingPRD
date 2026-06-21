"""Error classes and error-id -> HTTP status catalog (PRD §5)."""


class ApiError(Exception):
    """Carries a machine-readable error_id, a human message, and an HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Complete error catalog: error_id -> http status.
ERROR_CATALOG = {
    # Auth
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    # Not found
    "ERR_NOT_FOUND": 404,
    "ERR_SPONSOR_NOT_FOUND": 404,
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_WAGE_STEP_NOT_FOUND": 404,
    "ERR_MILESTONE_NOT_FOUND": 404,
    "ERR_JOURNEYWORKER_NOT_FOUND": 404,
    "ERR_APPRENTICE_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_OJT_ENTRY_NOT_FOUND": 404,
    "ERR_RTI_RECORD_NOT_FOUND": 404,
    "ERR_ATTAINMENT_NOT_FOUND": 404,
    "ERR_CERTIFICATE_NOT_FOUND": 404,
    "ERR_EEO_REPORT_NOT_FOUND": 404,
    # Input validation
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_INVALID_TIME_RANGE": 422,
    "ERR_DATE_BEFORE_AGREEMENT_START": 422,
    # Referential / sponsor scoping
    "ERR_SPONSOR_MISMATCH": 409,
    "ERR_MILESTONE_PROGRAM_MISMATCH": 409,
    "ERR_DUPLICATE_RESOURCE": 409,
    # OCC
    "ERR_STALE_VERSION": 412,
    # State: program
    "ERR_PROGRAM_NOT_DRAFT": 409,
    "ERR_PROGRAM_NOT_ACTIVE": 409,
    "ERR_NO_WAGE_STEPS": 409,
    "ERR_NO_BASE_WAGE_STEP": 409,
    "ERR_PROGRAM_HAS_OPEN_AGREEMENTS": 409,
    # State: journeyworker
    "ERR_JOURNEYWORKER_NOT_PROBATIONARY": 409,
    "ERR_JOURNEYWORKER_NOT_QUALIFIED": 409,
    "ERR_JOURNEYWORKER_HAS_APPRENTICES": 409,
    # State: agreement
    "ERR_AGREEMENT_NOT_DRAFT": 409,
    "ERR_AGREEMENT_NOT_REGISTERED": 409,
    "ERR_AGREEMENT_NOT_ACTIVE": 409,
    "ERR_AGREEMENT_NOT_SUSPENDED": 409,
    "ERR_AGREEMENT_NOT_CANCELLABLE": 409,
    # State: OJT / milestone attainment
    "ERR_OJT_ENTRY_NOT_PENDING": 409,
    "ERR_OJT_ENTRY_NOT_APPROVED": 409,
    "ERR_ATTAINMENT_NOT_SUBMITTED": 409,
    "ERR_ATTAINMENT_NOT_REJECTED": 409,
    # Business constraints
    "ERR_JOURNEYMAN_RATIO_EXCEEDED": 409,
    "ERR_COMPLETION_REQUIREMENTS_NOT_MET": 409,
    "ERR_APPRENTICE_SESSION_OVERLAP": 409,
    "ERR_JOURNEYWORKER_SUPERVISION_CONFLICT": 409,
}


def err(error_id, message=None):
    """Construct an ApiError using the catalog status for error_id."""
    return ApiError(error_id, ERROR_CATALOG.get(error_id, 400), message)
