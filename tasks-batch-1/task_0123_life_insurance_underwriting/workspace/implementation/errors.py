"""Error catalogue and the ApiError exception.

Every error_id below is taken verbatim from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status per error_id (PRD §5 error catalogue).
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_DUPLICATE_VALUE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_EVIDENCE_INCOMPLETE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_UNINSURABLE_RISK": 409,
    "ERR_OFFER_EXPIRED": 409,
    "ERR_REINSTATEMENT_WINDOW_CLOSED": 409,
    "ERR_PREMIUM_AMOUNT_MISMATCH": 422,
    "ERR_BENEFICIARY_SHARE_INVALID": 422,
    "ERR_LOAN_EXCEEDS_VALUE": 409,
    "ERR_FACE_EXCEEDS_PRODUCT_MAX": 409,
    "ERR_STALE_APPLICATION_VERSION": 412,
    "ERR_STALE_POLICY_VERSION": 412,
    "ERR_BACK_PREMIUM_INSUFFICIENT": 422,
    "ERR_EXAM_WINDOW_OVERLAP": 409,
    "ERR_COVERAGE_PERIOD_OVERLAP": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)
