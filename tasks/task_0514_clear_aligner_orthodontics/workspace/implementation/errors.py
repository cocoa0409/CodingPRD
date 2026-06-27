"""Error catalog and the ApiError exception type.

Every error_id and HTTP status comes from SCAFFOLD.yaml §1.6 / PRD §5.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> http status
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_CASE_VERSION": 412,
    "ERR_STALE_FINANCING_VERSION": 412,
    "ERR_CHANNEL_MISMATCH": 422,
    "ERR_INTAKE_FIELDS_INCOMPLETE": 422,
    "ERR_INTAKE_NOT_USABLE": 422,
    "ERR_NO_ELIGIBLE_CLINICIAN": 422,
    "ERR_CLINICIAN_NOT_LICENSED": 422,
    "ERR_GUARDIAN_CONSENT_REQUIRED": 422,
    "ERR_REFINEMENT_NOT_JUSTIFIED": 422,
    "ERR_STEP_ORDER_VIOLATION": 422,
    "ERR_GROUND_WINDOW_OVERLAP": 409,
    "ERR_EXPRESS_WINDOW_OVERLAP": 409,
    "ERR_WINDOW_INVERTED": 422,
    "ERR_DOWN_PAYMENT_EXCEEDS_TOTAL": 422,
    "ERR_INSTALLMENT_OUT_OF_ORDER": 422,
    "ERR_PAYMENT_NOT_SETTLED": 422,
    "ERR_CASE_NOT_COMPLETED": 422,
    "ERR_INVALID_REQUEST": 400,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
