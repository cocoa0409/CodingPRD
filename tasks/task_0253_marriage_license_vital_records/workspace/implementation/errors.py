"""Error classes and error-ID/HTTP-status catalog (PRD Section 5, SCAFFOLD 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else ERROR_STATUS.get(error_id, 400)
        self.message = message if message is not None else error_id
        super().__init__(self.message)


# error_id -> HTTP status code
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_DUPLICATE_APPLICANT": 409,
    "ERR_APPLICANT_ALREADY_MARRIED": 409,
    "ERR_AGE_INELIGIBLE": 409,
    "ERR_JUDICIAL_CONSENT_REQUIRED": 409,
    "ERR_REMARRIAGE_WAIT_NOT_MET": 409,
    "ERR_CEREMONY_BEFORE_VALID": 409,
    "ERR_CEREMONY_AFTER_EXPIRY": 409,
    "ERR_LICENSE_NOT_USABLE": 409,
    "ERR_LICENSE_ALREADY_USED": 409,
    "ERR_LICENSE_NOT_EXPIRED": 409,
    "ERR_OFFICIANT_NOT_AUTHORIZED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_CONFIDENTIAL_ACCESS_DENIED": 409,
    "ERR_RECORD_SEALED": 409,
    "ERR_RECORD_HAS_PENDING_COPIES": 409,
    "ERR_COPY_NOT_ISSUED": 409,
    "ERR_WAIVER_NOT_GRANTED": 409,
    "ERR_INCOME_ABOVE_THRESHOLD": 409,
    "ERR_RESUBMIT_LIMIT_REACHED": 409,
    "ERR_OFFICIANT_DOUBLE_BOOKED": 409,
    "ERR_APPLICANT_LICENSE_OVERLAP": 409,
}
