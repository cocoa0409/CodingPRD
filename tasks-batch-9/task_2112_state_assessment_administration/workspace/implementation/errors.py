"""Error catalogue (PRD section 5) and the exception type carrying it."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_SCOPE_VIOLATION": 403,
    "ERR_DISTRICT_NOT_FOUND": 404,
    "ERR_SCHOOL_NOT_FOUND": 404,
    "ERR_TEST_WINDOW_NOT_FOUND": 404,
    "ERR_PROCTOR_NOT_FOUND": 404,
    "ERR_SECURITY_AFFIDAVIT_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_REGISTRATION_NOT_FOUND": 404,
    "ERR_MATERIAL_LOT_NOT_FOUND": 404,
    "ERR_CUSTODY_EVENT_NOT_FOUND": 404,
    "ERR_IRREGULARITY_REPORT_NOT_FOUND": 404,
    "ERR_SCORE_APPEAL_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_PROCTOR_VERSION": 412,
    "ERR_STALE_SESSION_VERSION": 412,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_WINDOW_PHASE_INVALID": 409,
    "ERR_SESSION_NOT_ACCEPTING_REGISTRATIONS": 409,
    "ERR_LOT_NOT_AWAITING_RECONCILIATION": 409,
    "ERR_SCORE_NOT_RELEASED": 409,
    "ERR_RETURN_CYCLE_LIMIT": 409,
    "ERR_DUPLICATE_CODE": 409,
    "ERR_DUPLICATE_REGISTRATION": 409,
    "ERR_ROOM_TIME_CONFLICT": 409,
    "ERR_PROCTOR_TIME_CONFLICT": 409,
    "ERR_SESSION_OUTSIDE_WINDOW": 422,
    "ERR_TIMING_PRECONDITION_NOT_MET": 422,
    "ERR_APPEAL_WINDOW_CLOSED": 422,
    "ERR_PROCTOR_NOT_CERTIFIED": 422,
    "ERR_AFFIDAVIT_MISSING": 422,
    "ERR_CUSTODY_CHAIN_BROKEN": 422,
    "ERR_INSUFFICIENT_MATERIALS": 422,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_MAKEUP_NOT_ELIGIBLE": 422,
    "ERR_SESSION_CAPACITY_EXCEEDED": 422,
    "ERR_ACCOMMODATION_NOT_APPROVED": 422,
    "ERR_PARTICIPATION_BELOW_MINIMUM": 422,
    "ERR_SECURITY_HOLD_ACTIVE": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role must both be present and name a recognised role.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role may not perform this operation.",
    "ERR_SCOPE_VIOLATION": "The acting principal's scope does not cover the target resource.",
    "ERR_DISTRICT_NOT_FOUND": "District not found.",
    "ERR_SCHOOL_NOT_FOUND": "School not found.",
    "ERR_TEST_WINDOW_NOT_FOUND": "Test window not found.",
    "ERR_PROCTOR_NOT_FOUND": "Proctor not found.",
    "ERR_SECURITY_AFFIDAVIT_NOT_FOUND": "Security affidavit not found.",
    "ERR_SESSION_NOT_FOUND": "Session not found.",
    "ERR_REGISTRATION_NOT_FOUND": "Registration not found.",
    "ERR_MATERIAL_LOT_NOT_FOUND": "Material lot not found.",
    "ERR_CUSTODY_EVENT_NOT_FOUND": "Custody event not found.",
    "ERR_IRREGULARITY_REPORT_NOT_FOUND": "Irregularity report not found.",
    "ERR_SCORE_APPEAL_NOT_FOUND": "Score appeal not found.",
    "ERR_INVALID_REQUEST": "The request body is not well formed.",
    "ERR_STALE_PROCTOR_VERSION": "expected_proctor_version does not match the proctor's current version.",
    "ERR_STALE_SESSION_VERSION": "expected_session_version does not match the session's current version.",
    "ERR_INVALID_STATE_TRANSITION": "The requested state transition is not available.",
    "ERR_WINDOW_PHASE_INVALID": "The governing test window is not in a phase that permits this operation.",
    "ERR_SESSION_NOT_ACCEPTING_REGISTRATIONS": "The session is no longer accepting registrations.",
    "ERR_LOT_NOT_AWAITING_RECONCILIATION": "The material lot is not awaiting reconciliation.",
    "ERR_SCORE_NOT_RELEASED": "The score is not in a state that permits this operation.",
    "ERR_RETURN_CYCLE_LIMIT": "The report has already been returned for information the maximum number of times.",
    "ERR_DUPLICATE_CODE": "The supplied code is already in use.",
    "ERR_DUPLICATE_REGISTRATION": "A registration already exists for this student or original registration.",
    "ERR_ROOM_TIME_CONFLICT": "The room is already booked for an overlapping interval.",
    "ERR_PROCTOR_TIME_CONFLICT": "The proctor is already assigned to an overlapping session.",
    "ERR_SESSION_OUTSIDE_WINDOW": "The session interval does not sit inside its window phase.",
    "ERR_TIMING_PRECONDITION_NOT_MET": "The logical clock has not reached the instant this transition requires.",
    "ERR_APPEAL_WINDOW_CLOSED": "The appeal window has closed.",
    "ERR_PROCTOR_NOT_CERTIFIED": "The proctor is not certified.",
    "ERR_AFFIDAVIT_MISSING": "No active security affidavit exists for this proctor and window.",
    "ERR_CUSTODY_CHAIN_BROKEN": "The custody movement is not legal for the lot's current chain position.",
    "ERR_INSUFFICIENT_MATERIALS": "Not enough booklets are available for this movement.",
    "ERR_SEGREGATION_OF_DUTIES": "A make-up seat may not be proctored by the original session's proctor.",
    "ERR_MAKEUP_NOT_ELIGIBLE": "The named original registration is not eligible for a make-up seat.",
    "ERR_SESSION_CAPACITY_EXCEEDED": "The session's effective seat capacity would be exceeded.",
    "ERR_ACCOMMODATION_NOT_APPROVED": "A registration on this session is still awaiting district accommodation review.",
    "ERR_PARTICIPATION_BELOW_MINIMUM": "Provisional participation is below the window's minimum.",
    "ERR_SECURITY_HOLD_ACTIVE": "The window is under a security hold.",
}


def api_error(error_id, message=None):
    return ApiError(error_id, message)
