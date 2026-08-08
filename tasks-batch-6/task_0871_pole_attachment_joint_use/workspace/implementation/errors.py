"""Error class and the complete error catalogue (error_id -> HTTP status)."""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_POLE_OWNER_NOT_FOUND": 404,
    "ERR_CREW_NOT_FOUND": 404,
    "ERR_POLE_NOT_FOUND": 404,
    "ERR_ATTACHER_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_SURVEY_NOT_FOUND": 404,
    "ERR_ATTACHMENT_NOT_FOUND": 404,
    "ERR_FINDING_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_DUPLICATE_CIN": 409,
    "ERR_DUPLICATE_POLE_TAG": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_ESTIMATE_EXPIRED": 409,
    "ERR_POLE_NOT_ACTIVE": 409,
    "ERR_POLE_HAS_ATTACHMENTS": 409,
    "ERR_INVOICE_UNDER_DISPUTE": 409,
    "ERR_INVOICE_ALREADY_TERMINAL": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CREW_DOUBLE_BOOKED": 409,
    "ERR_CLEARANCE_VIOLATION": 409,
    "ERR_INSUFFICIENT_POLE_SPACE": 409,
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
    "ERR_DISPUTE_SUBJECT_INVALID": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id
