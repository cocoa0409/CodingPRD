"""Error catalogue (PRD section 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_HTTP_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # existence
    "ERR_OPERATOR_NOT_FOUND": 404,
    "ERR_FACILITY_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_PLAN_REVIEW_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_VIOLATION_NOT_FOUND": 404,
    "ERR_CLOSURE_ORDER_NOT_FOUND": 404,
    "ERR_COMPLAINT_NOT_FOUND": 404,
    "ERR_STAFF_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_READING_NOT_FOUND": 404,
    "ERR_LEDGER_ENTRY_NOT_FOUND": 404,
    # payload
    "ERR_VALIDATION": 400,
    "ERR_ARTIFACT_FIELDS_MISMATCH": 422,
    # referential consistency
    "ERR_PLAN_REVIEW_FACILITY_MISMATCH": 409,
    "ERR_PRIOR_INSPECTION_MISMATCH": 409,
    "ERR_READING_FACILITY_MISMATCH": 409,
    # optimistic concurrency
    "ERR_STALE_FACILITY_VERSION": 412,
    "ERR_STALE_PLAN_REVIEW_VERSION": 412,
    # state
    "ERR_INVALID_PERMIT_STATE": 409,
    "ERR_INVALID_PLAN_REVIEW_STATE": 409,
    "ERR_INVALID_INSPECTION_STATE": 409,
    "ERR_INVALID_ENFORCEMENT_STATE": 409,
    "ERR_INVALID_CLOSURE_STATE": 409,
    "ERR_INVALID_VIOLATION_STATE": 409,
    "ERR_INVALID_COMPLAINT_STATE": 409,
    "ERR_ASSIGNMENT_ALREADY_CANCELLED": 409,
    # safety / compliance
    "ERR_VGB_NONCOMPLIANT": 409,
    "ERR_OPEN_CRITICAL_VIOLATIONS": 409,
    "ERR_FACILITY_CLOSED": 409,
    "ERR_IMMINENT_HEALTH_HAZARD": 409,
    "ERR_WATER_NOT_IN_RANGE": 409,
    "ERR_REMEDIATION_INCOMPLETE": 409,
    "ERR_VERIFICATION_READING_STALE": 409,
    # temporal
    "ERR_INSPECTION_WINDOW_CONFLICT": 409,
    "ERR_OUT_OF_SEASON": 409,
    "ERR_SHIFT_TOO_LONG": 422,
    "ERR_CERTIFICATION_EXPIRED": 409,
    "ERR_STAFF_SHIFT_OVERLAP": 409,
    "ERR_SEASON_TERM_TOO_LONG": 422,
    "ERR_PERMIT_TERM_OVERLAP": 409,
    "ERR_RENEWAL_WINDOW_NOT_OPEN": 409,
    # referential business rules
    "ERR_PLAN_REVIEW_NOT_APPROVED": 409,
    "ERR_PLAN_REVIEW_ROUNDS_EXHAUSTED": 409,
    "ERR_INSPECTION_TYPE_REQUIRES_PRIOR": 422,
    # fiscal
    "ERR_OUTSTANDING_FEES": 402,
    "ERR_REFUND_NOT_ELIGIBLE": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or invalid authentication headers.",
    "ERR_UNAUTHORIZED": "The acting role may not use this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting operator does not own this resource.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this actor.",
    "ERR_VALIDATION": "The request payload failed validation.",
}
