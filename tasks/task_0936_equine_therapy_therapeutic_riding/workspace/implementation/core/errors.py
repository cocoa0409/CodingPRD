"""The 40-code error catalogue (PRD §5) and the exception that carries it."""

HTTP_BY_ERROR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_ENUM": 400,
    "ERR_RIDER_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_HORSE_NOT_FOUND": 404,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_INCIDENT_HOLD_ACTIVE": 409,
    "ERR_REPORT_FINALIZED": 409,
    "ERR_HORSE_ON_HOLD": 409,
    "ERR_INSTRUCTOR_CERT_LAPSED": 409,
    "ERR_RELEASE_MISSING": 422,
    "ERR_RELEASE_EXPIRED": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_RIDER_NOT_ACTIVE": 409,
    "ERR_REASSESSMENT_OVERDUE": 422,
    "ERR_CONDITION_POLICY_MISSING": 422,
    "ERR_CONDITION_CONTRAINDICATED": 422,
    "ERR_PRECAUTION_NOT_CLEARED": 422,
    "ERR_SUPERVISOR_REQUIRED": 422,
    "ERR_INSTRUCTOR_TIER_INSUFFICIENT": 422,
    "ERR_HORSE_LOAD_EXCEEDED": 422,
    "ERR_HORSE_SCHEDULE_CONFLICT": 409,
    "ERR_HORSE_REST_INTERVAL": 409,
    "ERR_HORSE_DAILY_LIMIT_EXCEEDED": 422,
    "ERR_HORSE_WEEKLY_MINUTES_EXCEEDED": 422,
    "ERR_INSTRUCTOR_SCHEDULE_CONFLICT": 409,
    "ERR_CREW_ROLE_NOT_REQUIRED": 422,
    "ERR_DUPLICATE_CREW_ASSIGNMENT": 409,
    "ERR_VOLUNTEER_SCHEDULE_CONFLICT": 409,
    "ERR_VOLUNTEER_SUSPENDED": 409,
    "ERR_VOLUNTEER_UNDER_AGE": 422,
    "ERR_VOLUNTEER_NOT_QUALIFIED": 422,
    "ERR_HOLD_TYPE_MISMATCH": 422,
    "ERR_CREW_INCOMPLETE": 409,
    "ERR_GRANT_RESTRICTION_VIOLATION": 422,
    "ERR_FUNDS_EXHAUSTED": 422,
    "ERR_CE_HOURS_INSUFFICIENT": 422,
    "ERR_STALE_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = HTTP_BY_ERROR[error_id]


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)
