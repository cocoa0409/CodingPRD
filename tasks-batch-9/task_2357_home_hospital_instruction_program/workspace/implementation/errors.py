"""Error vocabulary — the complete catalogue of PRD §5."""

ERROR_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_ASSIGNED_TEACHER": 403,
    "ERR_NOT_CLASSROOM_TEACHER_OF_RECORD": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # payload shape
    "ERR_VALIDATION": 400,
    # existence
    "ERR_STUDENT_NOT_FOUND": 404,
    "ERR_TEACHER_NOT_FOUND": 404,
    "ERR_ENTITLEMENT_RULE_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_CERTIFICATION_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_SAFETY_REVIEW_NOT_FOUND": 404,
    "ERR_EXTENSION_REQUEST_NOT_FOUND": 404,
    "ERR_TRANSITION_PLAN_NOT_FOUND": 404,
    "ERR_PACING_SYNC_NOT_FOUND": 404,
    "ERR_SPED_LOG_NOT_FOUND": 404,
    "ERR_LEDGER_ENTRY_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_CASE_VERSION": 412,
    # state preconditions
    "ERR_INVALID_CASE_STATE": 409,
    "ERR_CASE_NOT_ACTIVE": 409,
    "ERR_SESSION_ALREADY_LOGGED": 409,
    "ERR_SESSION_NOT_DELIVERED": 409,
    "ERR_SESSION_ALREADY_VERIFIED": 409,
    "ERR_CERT_NOT_REVIEWABLE": 409,
    "ERR_CERT_ALREADY_PENDING": 409,
    "ERR_ASSIGNMENT_NOT_PROPOSED": 409,
    "ERR_ASSIGNMENT_NOT_ACTIVE": 409,
    "ERR_ASSIGNMENT_HAS_SCHEDULED_SESSIONS": 409,
    "ERR_EXTENSION_STATE_INVALID": 409,
    "ERR_EXTENSION_RESUBMIT_LIMIT": 409,
    "ERR_PLAN_NOT_READY": 409,
    "ERR_PLAN_STATE_INVALID": 409,
    "ERR_PACING_ALREADY_ACKED": 409,
    "ERR_SPED_CONTINUATION_INVALID": 409,
    "ERR_FUNDING_NOT_ACCRUING": 409,
    "ERR_FUNDING_ALREADY_RECONCILED": 409,
    "ERR_REVIEW_ALREADY_FINALIZED": 409,
    "ERR_RULE_ALREADY_RETIRED": 409,
    # safety and compliance
    "ERR_SAFETY_REVIEW_MISSING": 422,
    "ERR_SAFETY_REVIEW_EXPIRED": 422,
    "ERR_SAFETY_CLEARANCE_BLOCKED": 422,
    "ERR_IN_HOME_NOT_PERMITTED": 422,
    "ERR_TEACHER_CLEARANCE_EXPIRED": 422,
    "ERR_ESCORT_REQUIRED_NOT_CONFIRMED": 422,
    # uniqueness and constraint satisfaction
    "ERR_DUPLICATE_STUDENT_NUMBER": 409,
    "ERR_DUPLICATE_ENTITLEMENT_RULE": 409,
    "ERR_DUPLICATE_PRIMARY_ASSIGNMENT": 409,
    "ERR_DUPLICATE_PACING_SUBJECT": 409,
    "ERR_DUPLICATE_SPED_SERVICE_TYPE": 409,
    "ERR_OPEN_CASE_EXISTS": 409,
    "ERR_SESSION_DURATION_INVALID": 422,
    "ERR_NO_PUBLISHED_ENTITLEMENT_RULE": 422,
    "ERR_ABSENCE_DURATION_TOO_SHORT": 422,
    "ERR_RAMP_WEEKS_INVALID": 422,
    # referential and cross-entity consistency
    "ERR_ASSIGNMENT_CASE_MISMATCH": 422,
    "ERR_CERT_CASE_MISMATCH": 422,
    "ERR_STUDENT_NOT_ENROLLED": 422,
    "ERR_CERT_NOT_ACCEPTED": 422,
    "ERR_CERT_WINDOW_INVALID": 422,
    "ERR_SESSION_OUTSIDE_CERT_WINDOW": 422,
    "ERR_NO_PACING_COORDINATION": 422,
    "ERR_SPED_SERVICE_SUSPENDED": 422,
    "ERR_NO_PRIMARY_ASSIGNMENT": 422,
    "ERR_MAKEUP_NOT_ELIGIBLE": 422,
    "ERR_TEACHER_BAND_MISMATCH": 422,
    # temporal conflicts
    "ERR_TEACHER_SLOT_CONFLICT": 409,
    "ERR_SESSION_GAP_TOO_SHORT": 409,
    "ERR_RETURN_DATE_NOT_REACHED": 409,
    # capacity, quota and fiscal limits
    "ERR_STUDENT_DAILY_LIMIT": 422,
    "ERR_TEACHER_CASELOAD_EXCEEDED": 422,
    "ERR_EXTENSION_LIMIT_REACHED": 422,
    "ERR_NO_ELIGIBLE_TEACHER": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or invalid authentication headers.",
    "ERR_UNAUTHORIZED": "The acting role is not authorized for this endpoint.",
    "ERR_NOT_ASSIGNED_TEACHER": "The acting user is not the assigned teacher.",
    "ERR_NOT_CLASSROOM_TEACHER_OF_RECORD": "The acting user is not the classroom teacher of record.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this actor from performing this action.",
    "ERR_VALIDATION": "The request payload or query is invalid.",
    "ERR_STALE_CASE_VERSION": "expected_case_version does not match the current case version.",
}


class ApiError(Exception):
    """An error carrying the machine-readable id, message and HTTP status."""

    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
        super().__init__(self.message)
