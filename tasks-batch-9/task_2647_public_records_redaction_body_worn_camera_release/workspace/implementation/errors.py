"""Error catalogue (PRD 5) and the exception type carrying it."""

ERROR_STATUS = {
    # -- auth ------------------------------------------------------------
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_REQUESTER_MISMATCH": 403,
    # -- schema ----------------------------------------------------------
    "ERR_VALIDATION": 400,
    # -- existence -------------------------------------------------------
    "ERR_REQUEST_NOT_FOUND": 404,
    "ERR_REQUESTER_NOT_FOUND": 404,
    "ERR_STAFF_NOT_FOUND": 404,
    "ERR_VIDEO_ASSET_NOT_FOUND": 404,
    "ERR_RESPONSIVE_RECORD_NOT_FOUND": 404,
    "ERR_EXEMPTION_CLAIM_NOT_FOUND": 404,
    "ERR_REDACTION_TASK_NOT_FOUND": 404,
    "ERR_DEPICTED_INDIVIDUAL_NOT_FOUND": 404,
    "ERR_DENIAL_LETTER_NOT_FOUND": 404,
    "ERR_LITIGATION_HOLD_NOT_FOUND": 404,
    "ERR_LEDGER_ENTRY_NOT_FOUND": 404,
    # -- concurrency -----------------------------------------------------
    "ERR_STALE_REQUEST_VERSION": 412,
    # -- state -----------------------------------------------------------
    "ERR_REQUEST_STATE_INVALID": 409,
    "ERR_FEE_STATE_INVALID": 409,
    "ERR_RECORD_STATE_INVALID": 409,
    "ERR_CLAIM_ALREADY_ADJUDICATED": 409,
    "ERR_TASK_STATE_INVALID": 409,
    "ERR_NOTIFICATION_STATE_INVALID": 409,
    "ERR_LETTER_STATE_INVALID": 409,
    "ERR_ASSET_STATE_INVALID": 409,
    "ERR_HOLD_STATE_INVALID": 409,
    "ERR_REQUEST_NOT_RELEASE_READY": 409,
    # -- safety / compliance ---------------------------------------------
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_CERTIFICATION_INSUFFICIENT": 422,
    "ERR_RECORD_RELEASE_BLOCKED": 409,
    "ERR_UNADJUDICATED_CLAIM": 409,
    "ERR_OBJECTION_UNRESOLVED": 409,
    "ERR_RETENTION_HOLD_ACTIVE": 409,
    # -- referential coherence -------------------------------------------
    "ERR_CLAIM_RECORD_MISMATCH": 422,
    "ERR_CITATION_MISMATCH": 422,
    # -- constraints -----------------------------------------------------
    "ERR_DUPLICATE_RESPONSIVE_RECORD": 409,
    "ERR_DUPLICATE_MATTER_NUMBER": 409,
    "ERR_DUPLICATE_DEPICTED_LABEL": 409,
    "ERR_ESTIMATE_BASIS_NOT_PERMITTED": 422,
    "ERR_INVALID_CLIP_RANGE": 422,
    "ERR_CLIP_OVERLAP": 409,
    "ERR_OPEN_REQUEST_LIMIT": 409,
    "ERR_SCOPE_CLARIFICATION_LIMIT": 409,
    "ERR_NO_RELEASABLE_RECORDS": 409,
    "ERR_QA_LOAD_EXCEEDED": 409,
    # -- temporal --------------------------------------------------------
    "ERR_INVALID_TIME_RANGE": 422,
    "ERR_QA_WINDOW_CONFLICT": 409,
    "ERR_WINDOW_CLOSED": 409,
    "ERR_PURGE_NOT_DUE": 409,
    # -- fiscal ----------------------------------------------------------
    "ERR_DEPOSIT_UNPAID": 402,
    "ERR_INVALID_AMOUNT": 422,
    "ERR_PAYMENT_EXCEEDS_OUTSTANDING": 422,
    "ERR_ENTRY_ALREADY_REVERSED": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
