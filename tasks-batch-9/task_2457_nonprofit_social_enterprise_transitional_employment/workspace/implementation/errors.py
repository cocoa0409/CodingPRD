"""Error catalogue (PRD section 5) and the exception type carrying it."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


# error_id -> http status
CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_BUSINESS_LINE_NOT_FOUND": 404,
    "ERR_REFERRAL_PARTNER_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_PARTICIPANT_NOT_FOUND": 404,
    "ERR_WORK_SHIFT_NOT_FOUND": 404,
    "ERR_SHIFT_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_SUPPORT_ACTIVITY_NOT_FOUND": 404,
    "ERR_EMPLOYER_NOT_FOUND": 404,
    "ERR_PLACEMENT_NOT_FOUND": 404,
    "ERR_RETENTION_CHECKPOINT_NOT_FOUND": 404,
    "ERR_SUBSIDY_PERIOD_NOT_FOUND": 404,
    "ERR_COST_ENTRY_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_SHIFT_NOT_SCHEDULED": 409,
    "ERR_PERIOD_CLOSED": 409,
    "ERR_STALE_BUSINESS_LINE_VERSION": 412,
    "ERR_STALE_SUBSIDY_PERIOD_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_GRADUATION_CRITERIA_NOT_MET": 422,
    "ERR_VIABILITY_GATE_NOT_MET": 422,
    "ERR_ELIGIBILITY_SCORE_BELOW_FLOOR": 422,
    "ERR_CHECKPOINT_NOT_DUE": 409,
    "ERR_PERIOD_NOT_ENDED": 409,
    "ERR_HIRE_DATE_BEFORE_GRADUATION": 422,
    "ERR_SHIFT_NOT_STARTED": 409,
    "ERR_PARTNER_MOU_LAPSED": 409,
    "ERR_INTAKE_CLOSED": 409,
    "ERR_EMPLOYER_NOT_ACTIVE": 409,
    "ERR_NO_OPEN_SUBSIDY_PERIOD": 409,
    "ERR_REVENUE_NOT_AVAILABLE": 409,
    "ERR_DUPLICATE_CANDIDATE_REFERENCE": 409,
    "ERR_REFERRAL_ALREADY_ENROLLED": 409,
    "ERR_RE_ENTRY_LIMIT_REACHED": 409,
    "ERR_DUPLICATE_SHIFT_ASSIGNMENT": 409,
    "ERR_CHECKPOINT_OUT_OF_SEQUENCE": 409,
    "ERR_SUBSIDY_PERIOD_OVERLAP": 409,
    "ERR_OPEN_ASSIGNMENTS_BLOCK_CLOSE": 409,
    "ERR_CATEGORY_NOT_MANUALLY_POSTABLE": 422,
    "ERR_PARTICIPANT_REST_BUFFER_CONFLICT": 409,
    "ERR_SUPERVISION_CAPACITY_EXCEEDED": 409,
    "ERR_SHIFT_CAPACITY_FULL": 409,
    "ERR_ACTUAL_HOURS_EXCEED_SHIFT": 422,
    "ERR_TRAINEE_WAGE_OUT_OF_RANGE": 422,
    "ERR_WAGE_BELOW_EMPLOYER_FLOOR": 422,
    "ERR_WAGE_PROGRESSION_FLOOR_NOT_MET": 422,
    "ERR_WEEKLY_HOURS_CAP_EXCEEDED": 409,
    "ERR_PARTNER_QUOTA_EXCEEDED": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be one of the seven declared roles.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not authorized for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting entity-backed role does not own the target resource.",
    "ERR_INVALID_REQUEST": "The request body or query does not conform to the endpoint input schema.",
    "ERR_INVALID_STATE_TRANSITION": "The target entity is not in a state from which the requested transition is declared.",
}


def fail(error_id, message=None):
    raise ApiError(error_id, CATALOG[error_id], message)
