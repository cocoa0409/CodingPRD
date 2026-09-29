"""Error catalogue and the ApiError exception.

Every error_id below is taken verbatim from PRD section 5 / SCAFFOLD errors[].
"""

ERROR_HTTP = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    # existence
    "ERR_SEASON_NOT_FOUND": 404,
    "ERR_TEAM_NOT_FOUND": 404,
    "ERR_ASSESSOR_NOT_FOUND": 404,
    "ERR_WRESTLER_NOT_FOUND": 404,
    "ERR_ASSESSMENT_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_EVENT_NOT_FOUND": 404,
    "ERR_ENTRY_NOT_FOUND": 404,
    "ERR_WEIGH_IN_NOT_FOUND": 404,
    "ERR_ELIGIBILITY_CHECK_NOT_FOUND": 404,
    "ERR_HEALTH_FLAG_NOT_FOUND": 404,
    "ERR_AUDIT_NOT_FOUND": 404,
    # schema / enum / range
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_WEIGHT_CLASS": 422,
    # optimistic concurrency
    "ERR_STALE_WRESTLER_VERSION": 412,
    "ERR_STALE_ENTRY_VERSION": 412,
    # state
    "ERR_SEASON_NOT_OPEN": 409,
    "ERR_SEASON_INVALID_STATE": 409,
    "ERR_ASSESSOR_INVALID_STATE": 409,
    "ERR_ASSESSMENT_INVALID_STATE": 409,
    "ERR_APPEAL_INVALID_STATE": 409,
    "ERR_PLAN_INVALID_STATE": 409,
    "ERR_EVENT_INVALID_STATE": 409,
    "ERR_ENTRY_INVALID_STATE": 409,
    "ERR_HEALTH_FLAG_INVALID_STATE": 409,
    "ERR_AUDIT_INVALID_STATE": 409,
    # safety / compliance
    "ERR_WRESTLER_DISQUALIFIED": 409,
    "ERR_WRESTLER_NOT_CERTIFIED": 409,
    "ERR_UNHEALTHY_WEIGHT_MANAGEMENT": 409,
    "ERR_CLASS_BELOW_CERTIFIED_MINIMUM": 422,
    "ERR_TARGET_BELOW_MINIMUM": 422,
    "ERR_NO_ELIGIBLE_WEIGHT_CLASS": 422,
    "ERR_DESCENT_RATE_EXCEEDED": 422,
    "ERR_ESCALATED_FLAG_REQUIRED": 409,
    # referential / segregation of duties
    "ERR_ASSESSOR_NOT_CERTIFIED": 409,
    "ERR_METHOD_NOT_CERTIFIED": 422,
    "ERR_SAME_ASSESSOR_CONFLICT": 409,
    "ERR_ASSESSMENT_WRESTLER_MISMATCH": 422,
    "ERR_AUDIT_SAMPLE_MISMATCH": 422,
    "ERR_TEAM_ON_PROBATION": 409,
    # temporal
    "ERR_APPEAL_WINDOW_EXPIRED": 422,
    "ERR_WEIGH_IN_DAY_OUT_OF_RANGE": 422,
    "ERR_ENTRY_WINDOW_CONFLICT": 409,
    # capacity / uniqueness / bracket
    "ERR_ASSESSOR_DAY_CAPACITY_EXCEEDED": 409,
    "ERR_DUPLICATE_ENTRY": 409,
    "ERR_DUPLICATE_WEIGH_IN": 409,
    "ERR_GROWTH_ALLOWANCE_DATE_CONFLICT": 409,
    "ERR_DUPLICATE_CREDENTIAL": 409,
    "ERR_DUPLICATE_SCHOOL_NAME": 409,
    "ERR_BRACKET_LOCKED": 409,
    "ERR_APPEAL_ROUND_LIMIT": 409,
    "ERR_NO_SEEDABLE_ENTRIES": 409,
    "ERR_RESEED_REQUIRED": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return "Request refused: %s." % words
