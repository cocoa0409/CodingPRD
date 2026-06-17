"""Error classes and the complete error catalogue (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status for each error_id, taken verbatim from PRD section 5.
ERROR_STATUS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_SLOT_INTERVAL": 400,
    "ERR_OCCURRED_IN_FUTURE": 400,
    "ERR_SCHEDULED_IN_PAST": 400,
    "ERR_STALE_RECORD_VERSION": 412,
    "ERR_RECORD_NOT_ELIGIBLE": 409,
    "ERR_RECORD_NOT_ACTIVE": 409,
    "ERR_RECORD_NOT_SUSPENDED": 409,
    "ERR_TEST_NOT_SCHEDULED": 409,
    "ERR_TEST_NOT_FAILED": 409,
    "ERR_TEST_NOT_YET_DUE": 409,
    "ERR_RETAKE_COOLDOWN": 409,
    "ERR_APPT_NOT_BOOKED": 409,
    "ERR_APPT_NOT_PROCTORED": 409,
    "ERR_SLOT_NOT_STARTED": 409,
    "ERR_SUSPENSION_NOT_SERVED": 409,
    "ERR_SUSPENSION_NOT_ACTIVE": 409,
    "ERR_VIOLATION_NOT_ACTIVE": 409,
    "ERR_CDL_NOT_DOWNGRADED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_ROAD_TEST_NOT_PASSED": 409,
    "ERR_REAL_ID_NOT_VERIFIED": 409,
    "ERR_KNOWLEDGE_TEST_REQUIRED": 409,
    "ERR_EXAMINER_MISMATCH": 403,
    "ERR_EXAMINER_NOT_CERTIFIED": 409,
    "ERR_NO_VALID_MEDICAL_CARD": 409,
    "ERR_VIOLATION_NOT_DISMISSED": 409,
    "ERR_EXAMINER_SLOT_CONFLICT": 409,
    "ERR_KNOWLEDGE_SITTING_CONFLICT": 409,
    "ERR_INSUFFICIENT_DOCUMENTS": 422,
    "ERR_NOT_YET_ELIGIBLE": 409,
    "ERR_REVOCATION_THRESHOLD_NOT_MET": 409,
    "ERR_REINSTATEMENT_FEE_UNPAID": 402,
    "ERR_RENEWAL_FEE_UNPAID": 402,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
