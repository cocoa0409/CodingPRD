"""Error catalog. Each ApiError carries error_id, message, http_status.

Error IDs and HTTP statuses are taken verbatim from PRD section 5 / scaffold
Table 1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status per error_id (PRD section 5).
_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_ASSIGNMENT_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_TAX_ID_REQUIRED": 422,
    "ERR_SHOPPER_NOT_CERTIFIED": 422,
    "ERR_FAMILY_MISMATCH": 422,
    "ERR_DUE_OUTSIDE_WINDOW": 422,
    "ERR_ROTATION_COOLDOWN": 409,
    "ERR_EVIDENCE_INCOMPLETE": 422,
    "ERR_SECTION_KEYS_MISMATCH": 422,
    "ERR_WEIGHTS_NOT_NORMALIZED": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_DISPUTE_ROUNDS_EXHAUSTED": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_DISPUTE_ALREADY_OPEN": 409,
    "ERR_SHOPPER_HAS_OPEN_ASSIGNMENTS": 409,
    "ERR_SCRIPT_IN_USE": 409,
    "ERR_WAVE_NOT_DRAINED": 409,
    "ERR_REIMBURSEMENT_NOT_ACCRUED": 409,
    "ERR_INVALID_REQUEST": 400,
}


def err(error_id, message=None):
    return ApiError(error_id, _STATUS[error_id], message)
