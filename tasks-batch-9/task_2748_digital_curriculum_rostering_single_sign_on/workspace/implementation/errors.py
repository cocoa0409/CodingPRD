"""Error catalogue. Every error_id and HTTP status comes from PRD section 5."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").lower()
        )


HTTP = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # existence
    "ERR_SCHOOL_NOT_FOUND": 404,
    "ERR_TERM_NOT_FOUND": 404,
    "ERR_TEACHER_NOT_FOUND": 404,
    "ERR_STUDENT_NOT_FOUND": 404,
    "ERR_SECTION_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_VENDOR_APP_NOT_FOUND": 404,
    "ERR_BUILDING_ALLOCATION_NOT_FOUND": 404,
    "ERR_APP_ACCOUNT_NOT_FOUND": 404,
    "ERR_SYNC_RUN_NOT_FOUND": 404,
    "ERR_ERROR_QUEUE_ITEM_NOT_FOUND": 404,
    # shape / concurrency
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_VENDOR_APP_VERSION": 412,
    # state
    "ERR_SCHOOL_CLOSED": 409,
    "ERR_TERM_NOT_ACTIVE": 409,
    "ERR_TERM_WINDOW_CLOSED": 422,
    "ERR_STUDENT_NOT_ENROLLED": 409,
    "ERR_TEACHER_SEPARATED": 409,
    "ERR_ENROLLMENT_NOT_DROPPABLE": 409,
    "ERR_VENDOR_APP_NOT_ACTIVE": 409,
    "ERR_VENDOR_APP_ALREADY_ACTIVATED": 409,
    "ERR_SYNC_RUN_STATE_INVALID": 409,
    "ERR_SYNC_RUN_SUPERSEDED": 409,
    "ERR_SEAT_ALREADY_RELEASED": 409,
    "ERR_ACCOUNT_DEPROVISIONED": 409,
    "ERR_ERROR_QUEUE_ITEM_NOT_OPEN": 409,
    "ERR_ARCHIVE_WINDOW_CLOSED": 409,
    # identity / password
    "ERR_ACCOUNT_LOCKED": 403,
    "ERR_PASSWORD_TOO_SHORT": 422,
    "ERR_PASSWORD_COMPLEXITY": 422,
    "ERR_DEPROVISION_NOT_DUE": 409,
    "ERR_IDENTIFIER_UNAVAILABLE": 422,
    # governance
    "ERR_BLOCKING_ERRORS_UNRESOLVED": 409,
    "ERR_MERGE_SUBJECT_MISMATCH": 422,
    # temporal
    "ERR_TERM_DATE_ORDER": 422,
    "ERR_EFFECTIVE_DATE_OUT_OF_TERM": 422,
    "ERR_DROP_BEFORE_ADD": 422,
    "ERR_STUDENT_SCHEDULE_CONFLICT": 409,
    "ERR_TEACHER_PERIOD_CONFLICT": 409,
    # referential
    "ERR_SCHOOL_MISMATCH": 422,
    # uniqueness / capacity
    "ERR_DUPLICATE_SIS_ID": 409,
    "ERR_DUPLICATE_ENROLLMENT": 409,
    "ERR_DUPLICATE_APP_ACCOUNT": 409,
    "ERR_SECTION_AT_CAPACITY": 409,
    "ERR_GRADE_BAND_OUT_OF_SCOPE": 422,
    "ERR_NO_ELIGIBLE_BUILDINGS": 422,
    "ERR_ALLOCATION_EXCEEDS_LICENSE": 409,
    "ERR_ALLOCATION_BELOW_CONSUMED": 409,
    # fiscal
    "ERR_BUILDING_ALLOCATION_EXHAUSTED": 409,
    "ERR_DISTRICT_SEATS_EXHAUSTED": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role may not perform this operation.",
    "ERR_SCOPE_VIOLATION": "The acting identity is outside its own scope.",
    "ERR_SEGREGATION_OF_DUTIES": "This action requires a second pair of eyes.",
    "ERR_INVALID_REQUEST": "The request body or query is malformed.",
    "ERR_STALE_VENDOR_APP_VERSION": "expected_vendor_app_version is stale.",
}
