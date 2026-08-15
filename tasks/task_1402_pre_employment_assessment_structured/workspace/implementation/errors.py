"""Error classes carrying error_id + http_status per the scaffold error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(msg="Missing or invalid authentication headers"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_forbidden(msg="Role not authorized for this endpoint"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def err_ownership(msg="Ownership check failed"):
    return ApiError("ERR_OWNERSHIP_MISMATCH", msg, 403)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_ref_not_found(msg="Referenced entity not found"):
    return ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND", msg, 404)


def err_invalid_request(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_invalid_state(msg="Invalid state for this operation"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_OWNERSHIP_MISMATCH": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCED_ENTITY_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_CYCLE_NOT_ACTIVE": 409,
    "ERR_CYCLE_FROZEN": 409,
    "ERR_REQUISITION_NOT_OPEN": 409,
    "ERR_CYCLE_NOT_CLOSED": 409,
    "ERR_CANDIDATE_WITHDRAWN": 409,
    "ERR_ASSESSMENT_NOT_COMPLETED": 409,
    "ERR_SESSION_NOT_COMPLETED": 409,
    "ERR_SESSION_NOT_ENDED": 422,
    "ERR_SESSIONS_STILL_SCHEDULED": 409,
    "ERR_SCORECARD_NOT_DRAFT": 409,
    "ERR_SCORECARD_NOT_SUBMITTED": 409,
    "ERR_ACCOMMODATION_NOT_PENDING": 409,
    "ERR_FEEDBACK_ALREADY_SENT": 409,
    "ERR_DECISION_NOT_FINALIZED": 409,
    "ERR_DECISION_ALREADY_FINALIZED": 409,
    "ERR_STALE_CYCLE_VERSION": 412,
    "ERR_STALE_GUIDE_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_INTERVIEWER_NOT_CALIBRATED": 422,
    "ERR_VENDOR_NOT_ACTIVE": 422,
    "ERR_INSTRUMENT_NOT_VALIDATED": 422,
    "ERR_GUIDE_NOT_APPROVED": 422,
    "ERR_GUIDE_PINNED": 409,
    "ERR_GUIDE_VERSION_MISMATCH": 422,
    "ERR_ADVERSE_IMPACT_UNRESOLVED": 422,
    "ERR_DUPLICATE_INSTRUMENT_CODE": 409,
    "ERR_DUPLICATE_CANDIDATE_REF": 409,
    "ERR_DUPLICATE_INVITATION": 409,
    "ERR_DUPLICATE_SCORECARD": 409,
    "ERR_DUPLICATE_CALIBRATION": 409,
    "ERR_PENDING_ACCOMMODATION_EXISTS": 409,
    "ERR_RUBRIC_WEIGHT_SUM": 400,
    "ERR_RUBRIC_TOO_FEW_ITEMS": 400,
    "ERR_RATINGS_EMPTY": 400,
    "ERR_RATING_COMPETENCY_MISMATCH": 400,
    "ERR_RATING_OUT_OF_RANGE": 400,
    "ERR_SCORE_OUT_OF_RANGE": 400,
    "ERR_SESSION_DURATION_INVALID": 400,
    "ERR_WINDOW_ORDER_INVALID": 400,
    "ERR_EXTENSION_OUT_OF_RANGE": 400,
    "ERR_RATIONALE_TOO_SHORT": 400,
    "ERR_FEEDBACK_TEXT_TOO_SHORT": 400,
    "ERR_INTERVIEWER_DOUBLE_BOOKED": 409,
    "ERR_CYCLE_DAILY_CAPACITY_EXCEEDED": 409,
    "ERR_QUORUM_NOT_MET": 422,
    "ERR_CONTENT_LEDGER_NEGATIVE": 422,
    "ERR_CONTENT_COPIES_OUTSTANDING": 422,
    "ERR_OUTSIDE_ADMINISTRATION_WINDOW": 422,
    "ERR_SCORECARD_WINDOW_CLOSED": 422,
    "ERR_RETENTION_EXPIRED": 422,
    "ERR_EVIDENCE_TYPE_MISSING": 422,
    "ERR_EVIDENCE_EXPIRED": 422,
    "ERR_PRACTICE_SCORE_BELOW_THRESHOLD": 422,
}


def api_err(error_id, message=None):
    return ApiError(error_id, message or error_id, ERROR_HTTP[error_id])
