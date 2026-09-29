"""Error catalogue (PRD section 5 / SCAFFOLD section 1.6)."""

ERROR_HTTP = {
    # ---- authentication / authorization ----
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    # ---- not found ----
    "ERR_INTERSECTION_NOT_FOUND": 404,
    "ERR_CORRIDOR_NOT_FOUND": 404,
    "ERR_REQUESTER_NOT_FOUND": 404,
    "ERR_COMPLAINT_NOT_FOUND": 404,
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_TIMING_PLAN_NOT_FOUND": 404,
    "ERR_PHASE_SPLIT_NOT_FOUND": 404,
    "ERR_PED_CHECK_NOT_FOUND": 404,
    "ERR_PRIORITY_CONFIG_NOT_FOUND": 404,
    "ERR_OBSERVATION_NOT_FOUND": 404,
    "ERR_EVALUATION_NOT_FOUND": 404,
    # ---- request shape ----
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_PAGINATION": 422,
    # ---- state ----
    "ERR_CORRIDOR_NOT_SCREENED": 409,
    "ERR_CORRIDOR_NOT_SELECTED": 409,
    "ERR_PROJECT_NOT_IN_DATA_COLLECTION": 409,
    "ERR_PROJECT_NOT_IN_PLAN_DEVELOPMENT": 409,
    "ERR_PROJECT_NOT_IMPLEMENTED": 409,
    "ERR_PROJECT_NOT_IN_FIELD_TUNING": 409,
    "ERR_PROJECT_NOT_IN_EVALUATION": 409,
    "ERR_PROJECT_TERMINAL": 409,
    "ERR_PLAN_NOT_DRAFT": 409,
    "ERR_PLAN_NOT_COORDINATED": 409,
    "ERR_PLAN_NOT_SUBMITTED": 409,
    "ERR_PED_CHECK_NOT_FAILING": 409,
    "ERR_CONFIG_NOT_PROPOSED": 409,
    "ERR_CONFIG_NOT_APPROVED": 409,
    "ERR_CONFIG_NOT_DEPLOYED": 409,
    "ERR_COMPLAINT_INVALID_STATE": 409,
    "ERR_EVALUATION_NOT_PROVISIONAL": 409,
    "ERR_OBSERVATION_NOT_OPEN": 409,
    "ERR_OBSERVATIONS_UNRESOLVED": 409,
    # ---- optimistic concurrency ----
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_STALE_INTERSECTION_VERSION": 412,
    # ---- safety / engineering standards ----
    "ERR_APS_STANDARD_MISMATCH": 422,
    "ERR_POSTURE_BLOCKS_CERTIFICATION": 409,
    "ERR_POSTURE_BLOCKS_DEPLOYMENT": 409,
    "ERR_PED_CLEARANCE_INSUFFICIENT": 422,
    "ERR_MIN_GREEN_VIOLATION": 422,
    "ERR_CYCLE_EXCEEDS_LOCAL_MAX": 422,
    "ERR_OVERSATURATED_APPROACH": 422,
    # ---- referential / study completeness ----
    "ERR_BEFORE_STUDY_INCOMPLETE": 409,
    "ERR_PLAN_COVERAGE_INCOMPLETE": 409,
    "ERR_COMPLAINT_PROJECT_MISMATCH": 422,
    "ERR_NO_AFTER_STUDY": 409,
    "ERR_NO_ELIGIBLE_MEMBERS": 409,
    "ERR_SCORE_BELOW_SELECT_THRESHOLD": 409,
    "ERR_CORRIDOR_PROJECT_ACTIVE": 409,
    # ---- temporal ----
    "ERR_STUDY_WINDOW_EXPIRED": 409,
    "ERR_TOD_WINDOW_OVERLAP": 409,
    "ERR_RUN_SPACING_VIOLATION": 409,
    "ERR_OBSERVATION_OUT_OF_WINDOW": 422,
    # ---- uniqueness / structural ----
    "ERR_DUPLICATE_REQUESTER_EMAIL": 409,
    "ERR_DUPLICATE_PRIORITY_RANK": 409,
    "ERR_DUPLICATE_PHASE_NUMBER": 409,
    "ERR_DUPLICATE_CORRIDOR_MEMBER": 409,
    "ERR_SEQUENCE_INDEX_GAP": 422,
    "ERR_DUPLICATE_TOD_PLAN": 409,
    # ---- budget / limit ----
    "ERR_TUNING_ROUND_LIMIT": 409,
    "ERR_PRIORITY_BUDGET_EXHAUSTED": 409,
    # ---- clock ----
    "ERR_CLOCK_NOT_MONOTONIC": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and must be non-blank.",
    "ERR_UNKNOWN_ROLE": "X-User-Role is not one of the six declared roles.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not authorised for this endpoint.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting user authored the artefact under review.",
    "ERR_NOT_RESOURCE_OWNER": "A PublicRequester may only act on their own requester row.",
    "ERR_INVALID_REQUEST": "The request body is invalid.",
    "ERR_INVALID_PAGINATION": "limit must be an integer in 1..100 and offset an integer >= 0.",
}


class ApiError(Exception):
    """An error carrying a catalogue error_id, its HTTP status and a message."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").lower().capitalize() + "."
        )


def fail(error_id, message=None):
    raise ApiError(error_id, message)
