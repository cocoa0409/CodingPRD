"""Error classes and the error catalog (ids -> HTTP status), per PRD section 5."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERROR_STATUS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_AGREEMENT_NOT_SIGNED": 409,
    "ERR_AGREEMENT_TERMINAL": 409,
    "ERR_ASSESSMENT_NOT_APPROVED": 409,
    "ERR_STALE_ASSESSMENT": 409,
    "ERR_QUOTE_EXPIRED": 409,
    "ERR_DELIVERY_MODE_MISMATCH": 409,
    "ERR_BELOW_MIN_ENROLLMENT": 409,
    "ERR_VENUE_CAPACITY_EXCEEDED": 409,
    "ERR_CREDENTIAL_EXPIRED": 409,
    "ERR_CREDENTIAL_MISMATCH": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_INSTRUCTOR_DOUBLE_BOOKED": 409,
    "ERR_VENUE_OVERLAP": 409,
    "ERR_DUPLICATE_PARTICIPANT": 409,
    "ERR_ATTENDANCE_ALREADY_CLOSED": 409,
    "ERR_SESSION_NOT_PLANNED": 409,
    "ERR_COHORT_NOT_CREDENTIALED": 409,
    "ERR_GRANT_PROGRAM_NOT_OPEN": 409,
    "ERR_GRANT_WINDOW_CLOSED": 409,
    "ERR_GRANT_CAPACITY_EXCEEDED": 409,
    "ERR_INVOICE_VARIANT_NOT_ALLOWED": 409,
    "ERR_INVOICE_NOT_PAYABLE": 409,
    "ERR_NO_COMPLETERS": 409,
    "ERR_OUTCOME_INCOMPLETE": 409,
}


def fail(error_id, message):
    status = ERROR_STATUS.get(error_id, 400)
    raise ApiError(error_id, message, status)
