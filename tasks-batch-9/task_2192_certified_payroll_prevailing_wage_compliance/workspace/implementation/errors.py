"""Error catalogue and the ApiError exception carrying error_id + HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)
        self.http_status = http_status if http_status is not None else HTTP_STATUS.get(error_id, 400)


HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_OWNER": 403,
    "ERR_STAFF_CAPABILITY_MISSING": 403,
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_SUBMISSION_NOT_FOUND": 404,
    "ERR_FINDING_NOT_FOUND": 404,
    "ERR_RESTITUTION_NOT_FOUND": 404,
    "ERR_INTERVIEW_NOT_FOUND": 404,
    "ERR_DETERMINATION_NOT_FOUND": 404,
    "ERR_CONTRACTOR_NOT_FOUND": 404,
    "ERR_STAFF_NOT_FOUND": 404,
    "ERR_WORKER_NOT_FOUND": 404,
    "ERR_FRINGE_PLAN_NOT_FOUND": 404,
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_PORTAL_NOT_FOUND": 404,
    # Not part of the declared 54; the only 404 available for GET /payroll-lines/{id}.
    "ERR_LINE_NOT_FOUND": 404,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_SUBMISSION_STATE": 409,
    "ERR_INVALID_FINDING_STATE": 409,
    "ERR_INVALID_ASSIGNMENT_STATE": 409,
    "ERR_INVALID_DETERMINATION_STATE": 409,
    "ERR_INVALID_INTERVIEW_STATE": 409,
    "ERR_INVALID_PAYMENT_STATE": 409,
    "ERR_INVALID_PROJECT_STATUS_TRANSITION": 409,
    "ERR_PROJECT_FROZEN": 409,
    "ERR_STALE_ASSIGNMENT_VERSION": 412,
    "ERR_STALE_FINDING_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_SOD_REVIEW_CONFLICT": 409,
    "ERR_NOTARIZATION_REQUIRED": 422,
    "ERR_CONTRACTOR_DEBARRED": 409,
    "ERR_APPRENTICE_PROGRAM_NOT_REGISTERED": 422,
    "ERR_APPRENTICE_TRADE_MISMATCH": 422,
    "ERR_APPRENTICE_PERIOD_OUT_OF_SCALE": 422,
    "ERR_NO_WAGE_RATE_FOR_CLASSIFICATION": 422,
    "ERR_FRINGE_PLAN_FOREIGN": 422,
    "ERR_FRINGE_PLAN_NOT_APPROVED": 422,
    "ERR_FRINGE_DOUBLE_COUNT": 422,
    "ERR_UPPER_TIER_NOT_ACTIVE": 409,
    "ERR_WEEK_ENDING_NOT_SATURDAY": 422,
    "ERR_PAYROLL_WEEK_NOT_ENDED": 422,
    "ERR_PAYROLL_WEEK_OVERLAP": 409,
    "ERR_DETERMINATION_PERIOD_OVERLAP": 409,
    "ERR_INTERVIEW_BUFFER_CONFLICT": 409,
    "ERR_SUBMISSION_WINDOW_CLOSED": 409,
    "ERR_DUPLICATE_WORKER_LINE": 409,
    "ERR_EMPTY_PAYROLL": 422,
    "ERR_APPRENTICE_RATIO_EXCEEDED": 422,
    "ERR_INVALID_SUPERSEDE_TARGET": 409,
    "ERR_RESTITUTION_EXCEEDS_OBLIGATION": 422,
    "ERR_RESTITUTION_ABOVE_COMPUTED_UNDERPAYMENT": 422,
    "ERR_OPEN_FINDINGS_BLOCK_CLOSEOUT": 409,
    "ERR_UNDERPAYMENT_UNRESOLVED": 409,
}

_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be one of the five declared roles.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorized for this endpoint.",
    "ERR_NOT_OWNER": "The acting contractor staff member does not belong to the owning contractor.",
    "ERR_STAFF_CAPABILITY_MISSING": "The acting contractor staff member lacks the required capability.",
    "ERR_VALIDATION": "Request body shape or field-level constraint violation.",
}
