"""Error types and the error catalog (id -> HTTP status)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Catalog from the PRD / scaffold (id: http status)
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_VALIDATION": 400,
    "ERR_FORBIDDEN": 403,
    "ERR_FORBIDDEN_SCOPE": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_AUDITOR_NOT_FOUND": 404,
    "ERR_CLASS_CODE_NOT_FOUND": 404,
    "ERR_WORK_ORDER_NOT_FOUND": 404,
    "ERR_RECORDS_REQUEST_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_ALLOCATION_NOT_FOUND": 404,
    "ERR_SUB_EXPOSURE_NOT_FOUND": 404,
    "ERR_CERTIFICATE_NOT_FOUND": 404,
    "ERR_AUDIT_RESULT_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_BILLING_NOT_FOUND": 404,
    "ERR_MOD_REVISION_NOT_FOUND": 404,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_APPOINTMENT_OUTSIDE_WINDOW": 409,
    "ERR_DISPUTE_WINDOW_CLOSED": 409,
    "ERR_APPOINTMENT_OVERLAP": 409,
    "ERR_ALLOCATION_PERIOD_OVERLAP": 409,
    "ERR_OPEN_RECORDS_REQUESTS": 409,
    "ERR_DRAFT_ALLOCATIONS_PENDING": 409,
    "ERR_RESCHEDULE_LIMIT_EXCEEDED": 409,
    "ERR_CERT_INSUFFICIENT_COVERAGE": 409,
    "ERR_CERT_WINDOW_INSUFFICIENT": 409,
    "ERR_AUDITOR_TERRITORY_MISMATCH": 409,
    "ERR_NO_NONCOMPLIANCE_BASIS": 409,
    "ERR_DUPLICATE_RECORDS_REQUEST": 409,
    "ERR_DUPLICATE_POLICY_NUMBER": 409,
    "ERR_DUPLICATE_CLASS_CODE": 409,
    "ERR_OVERPAYMENT": 422,
}


def raise_err(error_id, message=""):
    raise ApiError(error_id, message or error_id, ERRORS[error_id])


def validation(message):
    raise_err("ERR_VALIDATION", message)
