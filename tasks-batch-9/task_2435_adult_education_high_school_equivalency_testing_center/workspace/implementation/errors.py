"""Error catalogue and the ApiError exception (PRD section 5)."""

ERROR_STATUS = {
    # --- auth / request shape ------------------------------------------------
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_SCOPE": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    # --- not found ----------------------------------------------------------
    "ERR_STUDENT_NOT_FOUND": 404,
    "ERR_TESTING_CENTER_NOT_FOUND": 404,
    "ERR_TESTING_ROOM_NOT_FOUND": 404,
    "ERR_PROCTOR_NOT_FOUND": 404,
    "ERR_CLASS_SECTION_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_ATTENDANCE_ENTRY_NOT_FOUND": 404,
    "ERR_TEST_EVENT_NOT_FOUND": 404,
    "ERR_EXAM_SESSION_NOT_FOUND": 404,
    "ERR_EXAM_REGISTRATION_NOT_FOUND": 404,
    "ERR_ACCOMMODATION_REQUEST_NOT_FOUND": 404,
    "ERR_OUTCOME_RECORD_NOT_FOUND": 404,
    "ERR_CREDENTIAL_NOT_FOUND": 404,
    "ERR_TRANSCRIPT_ORDER_NOT_FOUND": 404,
    "ERR_FUNDING_PERIOD_NOT_FOUND": 404,
    # --- optimistic concurrency --------------------------------------------
    "ERR_STALE_EXAM_SESSION_VERSION": 412,
    "ERR_STALE_ENROLLMENT_VERSION": 412,
    "ERR_STALE_FUNDING_PERIOD_VERSION": 412,
    # --- state --------------------------------------------------------------
    "ERR_INVALID_INTAKE_STATE": 409,
    "ERR_STUDENT_NOT_ORIENTED": 409,
    "ERR_PLACEMENT_TEST_MISSING": 409,
    "ERR_STUDENT_NOT_PLACED": 409,
    "ERR_CENTER_DECISION_NOT_ALLOWED": 409,
    "ERR_CENTER_NOT_AUTHORIZED": 409,
    "ERR_CENTER_SUSPENDED": 409,
    "ERR_ROOM_OUT_OF_SERVICE": 409,
    "ERR_PROCTOR_DECISION_NOT_ALLOWED": 409,
    "ERR_SECTION_TRANSITION_NOT_ALLOWED": 409,
    "ERR_SECTION_NOT_ACCEPTING_ENROLLMENT": 409,
    "ERR_ENROLLMENT_NOT_ACTIVE": 409,
    "ERR_ATTENDANCE_ALREADY_VOIDED": 409,
    "ERR_TEST_EVENT_NOT_SCHEDULED": 409,
    "ERR_SESSION_NOT_ASSIGNABLE": 409,
    "ERR_SESSION_NOT_CANCELLABLE": 409,
    "ERR_SESSION_NOT_OPEN_FOR_REGISTRATION": 409,
    "ERR_REGISTRATION_NOT_OPEN": 409,
    "ERR_REGISTRATION_NOT_CHECKED_IN": 409,
    "ERR_IDENTITY_ALREADY_VERIFIED": 409,
    "ERR_ACCOMMODATION_NOT_PENDING": 409,
    "ERR_ACCOMMODATION_NOT_INFO_REQUESTED": 409,
    "ERR_OUTCOME_NOT_CERTIFIABLE": 409,
    "ERR_CREDENTIAL_NOT_ISSUED": 409,
    "ERR_TRANSCRIPT_ORDER_NOT_QUEUED": 409,
    "ERR_FUNDING_PERIOD_CLOSED": 409,
    # --- business safety ----------------------------------------------------
    "ERR_PROCTOR_NOT_CERTIFIED": 409,
    "ERR_PROCTOR_CERTIFICATION_LAPSED": 409,
    "ERR_IDENTITY_NOT_VERIFIED": 409,
    "ERR_SUBTEST_NOT_AUTHORIZED": 409,
    # --- business referential ----------------------------------------------
    "ERR_ACCOMMODATION_OWNER_MISMATCH": 409,
    "ERR_ACCOMMODATION_NOT_APPROVED": 409,
    "ERR_ACCOMMODATION_EXPIRED": 409,
    "ERR_ACCOMMODATION_FORMAT_UNAVAILABLE": 409,
    "ERR_OUTCOME_EVIDENCE_MISMATCH": 409,
    "ERR_MSG_NOT_SUPPORTED": 409,
    # --- business temporal --------------------------------------------------
    "ERR_SESSION_IN_PAST": 422,
    "ERR_POST_TEST_INTERVAL_NOT_MET": 409,
    "ERR_INVALID_SESSION_WINDOW": 422,
    "ERR_CHECK_IN_WINDOW_CLOSED": 409,
    "ERR_INVALID_EFFECTIVE_WINDOW": 422,
    "ERR_CLOCK_BACKWARD": 422,
    # --- business constraint ------------------------------------------------
    "ERR_POST_TEST_HOURS_NOT_MET": 409,
    "ERR_ROOM_BUFFER_CONFLICT": 409,
    "ERR_PROCTOR_TIME_CONFLICT": 409,
    "ERR_PROCTOR_DAILY_CAP_EXCEEDED": 409,
    "ERR_DUPLICATE_ACTIVE_ENROLLMENT": 409,
    "ERR_EFL_LEVEL_OUT_OF_RANGE": 409,
    "ERR_TEST_EVENT_CONFLICT": 409,
    "ERR_DUPLICATE_CREDENTIAL": 409,
    "ERR_CREDENTIAL_REQUIREMENTS_NOT_MET": 409,
    "ERR_INFO_REQUEST_LIMIT_REACHED": 409,
    "ERR_SECTION_CAPACITY_EXCEEDED": 409,
    "ERR_SESSION_SEATS_EXHAUSTED": 409,
    "ERR_DUPLICATE_REGISTRATION": 409,
    # --- business fiscal ----------------------------------------------------
    "ERR_VOUCHER_INSUFFICIENT": 402,
    "ERR_VOUCHER_ADJUSTMENT_INVALID": 422,
}


class ApiError(Exception):
    """An error that is rendered into the standard error envelope."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return "Request refused: %s." % words
