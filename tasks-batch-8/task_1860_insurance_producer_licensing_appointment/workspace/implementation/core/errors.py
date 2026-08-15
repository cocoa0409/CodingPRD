"""Error catalogue (PRD section 5) and the ApiError exception."""


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_SOD_VIOLATION": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_PRODUCER_SUSPENDED": 409,
    "ERR_LICENSE_NOT_ACTIVE": 409,
    "ERR_CE_INCOMPLETE": 409,
    "ERR_CE_NOT_APPLICABLE": 409,
    "ERR_DUPLICATE_LICENSE": 409,
    "ERR_APPOINTMENT_NOT_ACTIVE": 409,
    "ERR_APPOINTMENT_ALREADY_ACTIVE": 409,
    "ERR_APPOINTMENT_INTERVAL_OVERLAP": 409,
    "ERR_JIT_FILING_WINDOW_CLOSED": 409,
    "ERR_RENEWAL_WINDOW_CLOSED": 409,
    "ERR_TERMINATION_FILING_OVERDUE": 409,
    "ERR_HOLD_NOT_RELEASABLE": 409,
    "ERR_REGULATORY_HOLD_ACTIVE": 409,
    "ERR_COMMISSION_NOT_PAYABLE": 409,
    "ERR_PREMIUM_BELOW_MINIMUM": 422,
    "ERR_PROBATION_SPACING": 409,
    "ERR_OVERDUE_INQUIRY_EXISTS": 409,
    "ERR_LICENSE_SUBJECT_CONFLICT": 422,
}


class ApiError(Exception):
    """Raised by any rung of the PRD section 2.9 validation ladder."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = ERROR_STATUS[error_id]


def _default_message(error_id):
    return "Request refused: {}.".format(error_id)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
