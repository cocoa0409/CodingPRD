"""Error class and the full error catalog (PRD §5 / SCAFFOLD §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> http status
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_OWNER": 403,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_TIME_RANGE": 400,
    "ERR_PROCEDURE_NOT_FOUND": 404,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_CONSULTATION_NOT_FOUND": 404,
    "ERR_QUOTE_NOT_FOUND": 404,
    "ERR_LINE_ITEM_NOT_FOUND": 404,
    "ERR_CONSENT_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_FINANCING_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_OPEN_QUOTE_EXISTS": 409,
    "ERR_EMPTY_QUOTE": 409,
    "ERR_PROCEDURE_RETIRED": 409,
    "ERR_CONSENT_MISSING": 409,
    "ERR_CLEARANCE_MISSING": 409,
    "ERR_QUOTE_NOT_ACCEPTED": 409,
    "ERR_BOOKING_NOT_COMPLETED": 409,
    "ERR_SURGERY_NOT_STARTED": 409,
    "ERR_SURGERY_IN_PAST": 409,
    "ERR_OR_DOUBLE_BOOKED": 409,
    "ERR_SURGEON_BUFFER_CONFLICT": 409,
    "ERR_DEPOSIT_UNPAID": 402,
    "ERR_FINANCING_EXCEEDS_BALANCE": 402,
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
