"""Error catalog and ApiError exception. HTTP statuses per PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Complete error catalog: error_id -> http_status (PRD §5 / scaffold §1.6)
ERROR_STATUS = {
    # auth
    "ERR_MISSING_AUTH_CONTEXT": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_JOB_OWNER": 403,
    # not found
    "ERR_JOB_NOT_FOUND": 404,
    "ERR_TECHNICIAN_NOT_FOUND": 404,
    "ERR_BAY_NOT_FOUND": 404,
    "ERR_QUOTE_NOT_FOUND": 404,
    "ERR_DISPATCH_NOT_FOUND": 404,
    "ERR_LOCKPART_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    "ERR_PAYMENT_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    # request validation
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_ENUM": 422,
    "ERR_INVALID_TIME_WINDOW": 422,
    "ERR_INVALID_QUANTITY": 422,
    "ERR_QUOTE_INCOMPLETE": 422,
    # job state
    "ERR_JOB_NOT_DISPATCHABLE": 409,
    "ERR_JOB_NOT_ON_SITE": 409,
    "ERR_JOB_NOT_CANCELLABLE": 409,
    "ERR_JOB_NOT_CLOSED": 409,
    "ERR_JOB_NOT_FULLY_PAID": 409,
    "ERR_NO_APPROVED_QUOTE": 409,
    # dispatch / technician state
    "ERR_DISPATCH_NOT_ASSIGNED": 409,
    "ERR_DISPATCH_NOT_EN_ROUTE": 409,
    "ERR_DISPATCH_NOT_CANCELLABLE": 409,
    "ERR_TECHNICIAN_UNAVAILABLE": 409,
    "ERR_TECHNICIAN_NOT_CERTIFIED": 409,
    "ERR_ETA_WINDOW_OVERLAP": 409,
    # bay
    "ERR_BAY_SLOT_OVERLAP": 409,
    "ERR_BAY_NOT_OPEN": 409,
    # quote state
    "ERR_QUOTE_INVALID_STATE": 409,
    "ERR_QUOTE_ALREADY_APPROVED": 409,
    # inventory / parts
    "ERR_PART_DISCONTINUED": 409,
    "ERR_AUTHORIZATION_MISSING": 403,
    "ERR_INSUFFICIENT_STOCK": 409,
    "ERR_STALE_LOCKPART_VERSION": 412,
    # payment / warranty
    "ERR_PAYMENT_EXCEEDS_DUE": 409,
    "ERR_REFUND_EXCEEDS_PAID": 409,
    "ERR_WARRANTY_EXPIRED": 409,
    "ERR_CLAIM_INVALID_STATE": 409,
}


def err(error_id, message=None):
    """Build an ApiError using the catalog's HTTP status for the given id."""
    return ApiError(error_id, ERROR_STATUS[error_id], message)
