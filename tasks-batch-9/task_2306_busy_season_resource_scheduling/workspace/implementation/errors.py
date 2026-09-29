"""Error catalogue (PRD section 5 / SCAFFOLD errors)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)
        self.http_status = HTTP_STATUS.get(error_id, 400)


HTTP_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_INVALID_ROLE": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    # not-found family
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_STAFF_MEMBER_NOT_FOUND": 404,
    "ERR_ENGAGEMENT_NOT_FOUND": 404,
    "ERR_PHASE_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_RESTRICTION_NOT_FOUND": 404,
    "ERR_REVIEW_WINDOW_NOT_FOUND": 404,
    "ERR_RESCHEDULE_PLAN_NOT_FOUND": 404,
    "ERR_WAIVER_NOT_FOUND": 404,
    # request shape / geometry
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_PAGINATION": 422,
    "ERR_INVALID_DATE_RANGE": 422,
    "ERR_NOT_WEEK_START": 422,
    # invalid-state family
    "ERR_ENGAGEMENT_INVALID_STATE": 409,
    "ERR_PHASE_INVALID_STATE": 409,
    "ERR_ASSIGNMENT_INVALID_STATE": 409,
    "ERR_REVIEW_INVALID_STATE": 409,
    "ERR_RESTRICTION_INVALID_STATE": 409,
    "ERR_PLAN_INVALID_STATE": 409,
    "ERR_WAIVER_INVALID_STATE": 409,
    # containers / compliance
    "ERR_ENGAGEMENT_BLOCKED": 409,
    "ERR_PHASE_NOT_IN_PROGRESS": 409,
    "ERR_INDEPENDENCE_RESTRICTED": 409,
    "ERR_PARTNER_ROTATION_LIMIT": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_TURNOVER_RISK_BLOCK": 409,
    # skill profile
    "ERR_LEVEL_MISMATCH": 422,
    "ERR_SPECIALIZATION_MISMATCH": 422,
    "ERR_LICENSURE_REQUIRED": 422,
    "ERR_REVIEW_OWNER_REQUIRED": 422,
    "ERR_REVIEW_OWNER_NOT_ELIGIBLE": 422,
    "ERR_REVIEW_WINDOW_MISSING": 422,
    # uniqueness
    "ERR_DUPLICATE_ENGAGEMENT_YEAR": 409,
    "ERR_DUPLICATE_REVIEW_WINDOW": 409,
    "ERR_DUPLICATE_WAIVER": 409,
    "ERR_DUPLICATE_RESTRICTION": 409,
    # temporal geometry
    "ERR_PHASE_WINDOW_AFTER_DEADLINE": 422,
    "ERR_ASSIGNMENT_OUTSIDE_PHASE_WINDOW": 422,
    "ERR_EXCEPTION_OVERLAP": 409,
    "ERR_STAFF_UNAVAILABLE": 409,
    # capacity
    "ERR_DAILY_CAPACITY_EXCEEDED": 409,
    "ERR_WORKLOAD_CAP_EXCEEDED": 409,
    "ERR_REVIEW_CAPACITY_EXCEEDED": 409,
    "ERR_REWORK_LIMIT_EXCEEDED": 409,
    "ERR_TIME_ENTRY_OUT_OF_WINDOW": 422,
    "ERR_TIME_ENTRY_EXCEEDS_ALLOCATION": 409,
    # projection / selector
    "ERR_SIMULATION_STALE": 409,
    "ERR_PHASE_FULLY_STAFFED": 409,
    "ERR_NO_ELIGIBLE_STAFF": 422,
    # optimistic concurrency
    "ERR_STALE_PHASE_VERSION": 412,
    "ERR_STALE_ENGAGEMENT_VERSION": 412,
    # partner eligibility
    "ERR_PARTNER_LEVEL_REQUIRED": 422,
}

_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Both X-User-ID and X-User-Role headers are required.",
    "ERR_INVALID_ROLE": "X-User-Role is not a recognised role.",
    "ERR_UNAUTHORIZED": "The presented role may not call this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting user does not own the target resource.",
    "ERR_INVALID_REQUEST": "The request body is invalid.",
    "ERR_INVALID_PAGINATION": "limit must be an integer in [1, 100] and offset an integer >= 0.",
    "ERR_INVALID_DATE_RANGE": "The supplied date range is not well formed.",
    "ERR_NOT_WEEK_START": "week_start_date must be a Monday.",
}
