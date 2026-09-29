"""Error catalogue (PRD section 5) and the ApiError exception."""


ERROR_HTTP = {
    # auth / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    # existence
    "ERR_DISTRICT_NOT_FOUND": 404,
    "ERR_SCHOOL_NOT_FOUND": 404,
    "ERR_COACH_NOT_FOUND": 404,
    "ERR_STUDENT_NOT_FOUND": 404,
    "ERR_TITLE_NOT_FOUND": 404,
    "ERR_TITLE_APPROVAL_NOT_FOUND": 404,
    "ERR_SEASON_NOT_FOUND": 404,
    "ERR_TEAM_NOT_FOUND": 404,
    "ERR_ROSTER_SLOT_NOT_FOUND": 404,
    "ERR_MATCH_NOT_FOUND": 404,
    "ERR_FAIR_PLAY_CASE_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_GPA_THRESHOLDS": 422,
    "ERR_SELF_MATCH_FORBIDDEN": 422,
    "ERR_SUBJECT_REFERENCE_MISMATCH": 422,
    # optimistic concurrency
    "ERR_STALE_VERSION": 412,
    # state
    "ERR_INVALID_SEASON_STAGE": 409,
    "ERR_SEASON_SEEDING_NOT_CURRENT": 409,
    "ERR_INVALID_TEAM_STATE": 409,
    "ERR_ROSTER_LOCKED": 409,
    "ERR_ROSTER_SLOT_RELEASED": 409,
    "ERR_INVALID_MATCH_STATE": 409,
    "ERR_INVALID_DISPUTE_STATE": 409,
    "ERR_INVALID_BROADCAST_STATE": 409,
    "ERR_INVALID_CASE_STATE": 409,
    "ERR_INVALID_APPROVAL_STATE": 409,
    # business safety
    "ERR_COACH_NOT_CERTIFIED": 409,
    "ERR_COACH_BACKGROUND_CHECK_EXPIRED": 409,
    "ERR_STUDENT_NOT_ENROLLED": 422,
    "ERR_ENROLLMENT_CERTIFICATION_LAPSED": 422,
    "ERR_BIRTHDATE_DOCUMENT_MISMATCH": 422,
    "ERR_STUDENT_BELOW_TITLE_MIN_AGE": 422,
    "ERR_STUDENT_OVER_AGE_LIMIT": 422,
    "ERR_ACADEMIC_STANDING_INELIGIBLE": 422,
    "ERR_PROBATION_STARTER_RESTRICTED": 422,
    "ERR_STUDENT_FAIR_PLAY_SANCTIONED": 409,
    "ERR_TITLE_AGE_RATING_EXCEEDS_DISTRICT_CEILING": 422,
    "ERR_TITLE_NOT_DISTRICT_APPROVED": 409,
    # business referential
    "ERR_STUDENT_SCHOOL_MISMATCH": 422,
    "ERR_COACH_SCHOOL_MISMATCH": 422,
    "ERR_TEAM_TITLE_MISMATCH": 422,
    "ERR_TEAM_SEASON_MISMATCH": 422,
    "ERR_TEAM_NOT_MATCH_PARTICIPANT": 422,
    "ERR_BROADCAST_SCHOOL_MISMATCH": 422,
    "ERR_SUBJECT_TEAM_MISMATCH": 422,
    "ERR_STUDENT_NOT_ON_TEAM": 422,
    # business temporal
    "ERR_REGISTRATION_WINDOW_CLOSED": 409,
    "ERR_ROSTER_LOCK_DEADLINE_PASSED": 409,
    "ERR_MATCH_OUTSIDE_SEASON_WINDOW": 409,
    "ERR_SERVER_POOL_CAPACITY_EXCEEDED": 409,
    "ERR_BROADCAST_CHANNEL_CONFLICT": 409,
    "ERR_DISPUTE_WINDOW_CLOSED": 409,
    "ERR_RECRUITING_DEAD_PERIOD": 409,
    "ERR_CLOCK_REWIND_FORBIDDEN": 409,
    # business constraint
    "ERR_DUPLICATE_NCES_CODE": 409,
    "ERR_DUPLICATE_TITLE_NAME": 409,
    "ERR_DUPLICATE_TEAM_NAME": 409,
    "ERR_DUPLICATE_TITLE_APPROVAL": 409,
    "ERR_DUPLICATE_ROSTER_SLOT": 409,
    "ERR_STARTER_CAPACITY_EXCEEDED": 409,
    "ERR_ROSTER_MINIMUM_NOT_MET": 422,
    "ERR_ALREADY_NOMINATED": 409,
    "ERR_SHOWCASE_NOT_NOMINATED": 409,
    "ERR_RECRUITING_CONTACT_CAP_EXCEEDED": 409,
    "ERR_SEED_ORDER_EMPTY": 422,
    # business fiscal
    "ERR_SUBSIDY_POOL_EXHAUSTED": 402,
    # fallback for unroutable requests
    "ERR_NOT_FOUND": 404,
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline to abort with a catalogued error."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)


def _default_message(error_id):
    words = error_id.replace("ERR_", "").replace("_", " ").lower()
    return "Request rejected: %s." % words


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# Path-segment / body-FK error ids keyed by entity kind.
NOT_FOUND_FOR = {
    "district": "ERR_DISTRICT_NOT_FOUND",
    "school": "ERR_SCHOOL_NOT_FOUND",
    "coach": "ERR_COACH_NOT_FOUND",
    "student": "ERR_STUDENT_NOT_FOUND",
    "title": "ERR_TITLE_NOT_FOUND",
    "title_approval": "ERR_TITLE_APPROVAL_NOT_FOUND",
    "season": "ERR_SEASON_NOT_FOUND",
    "team": "ERR_TEAM_NOT_FOUND",
    "roster_slot": "ERR_ROSTER_SLOT_NOT_FOUND",
    "match": "ERR_MATCH_NOT_FOUND",
    "fair_play_case": "ERR_FAIR_PLAY_CASE_NOT_FOUND",
}
