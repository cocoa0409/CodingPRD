"""Error catalogue (PRD 5) and the exception type used to surface them."""

ERROR_HTTP = {
    # --- authentication / authorization ---
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_ATHLETE_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- existence ---
    "ERR_ATHLETE_NOT_FOUND": 404,
    "ERR_INJURY_RECORD_NOT_FOUND": 404,
    "ERR_TEST_SESSION_NOT_FOUND": 404,
    "ERR_TRAINING_PROGRAM_NOT_FOUND": 404,
    "ERR_PROGRAM_BLOCK_NOT_FOUND": 404,
    "ERR_GROUP_SESSION_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_STAFF_MEMBER_NOT_FOUND": 404,
    "ERR_CERTIFICATION_NOT_FOUND": 404,
    "ERR_MEMBERSHIP_PACKAGE_NOT_FOUND": 404,
    "ERR_TEAM_CONTRACT_NOT_FOUND": 404,
    "ERR_RTS_PLAN_NOT_FOUND": 404,
    "ERR_CLEARANCE_DOCUMENT_NOT_FOUND": 404,
    # --- schema / clock ---
    "ERR_INVALID_REQUEST": 422,
    "ERR_CLOCK_REWIND_FORBIDDEN": 422,
    # --- concurrency ---
    "ERR_STALE_VERSION": 412,
    # --- state ---
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_ATHLETE_SUSPENDED": 409,
    "ERR_DUPLICATE_ENROLLMENT": 409,
    # --- athlete safety ---
    "ERR_MOVEMENT_SCREEN_REQUIRED": 422,
    "ERR_ATHLETE_MEDICAL_HOLD": 422,
    "ERR_STAGE_CLEARANCE_MISSING": 422,
    "ERR_CLEARANCE_EXPIRED": 422,
    # --- staff safety ---
    "ERR_STAFF_CREDENTIAL_LAPSED": 422,
    "ERR_CEU_REQUIREMENT_NOT_MET": 422,
    # --- business constraints ---
    "ERR_SESSION_FULL": 422,
    "ERR_COACH_RATIO_EXCEEDED": 422,
    "ERR_READINESS_BELOW_THRESHOLD": 422,
    "ERR_RESTRICTED_PHASE_NOT_PERMITTED": 422,
    "ERR_PROGRAM_BLOCK_SEQUENCE_INVALID": 422,
    # --- temporal ---
    "ERR_STAFF_SCHEDULE_CONFLICT": 409,
    "ERR_TRAVEL_BUFFER_VIOLATION": 409,
    "ERR_ATHLETE_SCHEDULE_CONFLICT": 409,
    "ERR_SITE_CONCURRENCY_EXCEEDED": 409,
    "ERR_ENROLLMENT_WINDOW_CLOSED": 409,
    # --- referential ---
    "ERR_NORM_BAND_UNAVAILABLE": 422,
    "ERR_NO_TEST_RESULTS": 422,
    "ERR_CONTRACT_NOT_ACTIVE": 422,
    "ERR_VOID_BLOCKED_BY_NO_SHOW": 409,
    # --- fiscal ---
    "ERR_NO_SESSION_CREDIT": 402,
    "ERR_PACKAGE_EXPIRED": 402,
    "ERR_OFFSITE_ALLOWANCE_EXHAUSTED": 402,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
