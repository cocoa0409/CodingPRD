"""Error classes and error-id -> HTTP status catalog."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status if http_status is not None else ERROR_STATUS.get(error_id, 400)


# Complete error catalog (PRD §5)
ERROR_STATUS = {
    # Auth
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    # Request validation
    "ERR_INVALID_REQUEST": 400,
    # Not found
    "ERR_PROVIDER_NOT_FOUND": 404,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_MEMBERSHIP_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_CONSULTATION_NOT_FOUND": 404,
    "ERR_STANDING_ORDER_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    # OCC
    "ERR_STALE_PLAN_VERSION": 412,
    "ERR_STALE_LOT_VERSION": 412,
    "ERR_STALE_PROVIDER_VERSION": 412,
    "ERR_STALE_STANDING_ORDER_VERSION": 412,
    # State preconditions
    "ERR_CONSULTATION_NOT_DRAFT": 409,
    "ERR_CONSULTATION_IN_USE": 409,
    "ERR_PLAN_NOT_PROPOSED": 409,
    "ERR_PLAN_NOT_ACTIVE": 409,
    "ERR_PLAN_NOT_CANCELLABLE": 409,
    "ERR_PLAN_HAS_COMMITTED_SESSIONS": 409,
    "ERR_OPEN_SESSIONS_EXIST": 409,
    "ERR_SESSION_NOT_BOOKED": 409,
    "ERR_SESSION_NOT_COMMITTED": 409,
    "ERR_CASE_NOT_OPEN": 409,
    "ERR_CASE_NOT_IN_TOUCHUP": 409,
    "ERR_COMPLICATION_OPEN": 409,
    # Business safety / compliance
    "ERR_NO_GOOD_FAITH_EXAM": 409,
    "ERR_GOOD_FAITH_EXAM_EXPIRED": 409,
    "ERR_STANDING_ORDER_INACTIVE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_PROVIDER_NOT_ELIGIBLE": 409,
    "ERR_CONSENT_PHOTO_REQUIRED": 409,
    "ERR_BEFORE_PHOTO_REQUIRED": 409,
    "ERR_AFTER_PHOTO_REQUIRED": 409,
    # Business constraints
    "ERR_PRODUCT_MISMATCH": 422,
    "ERR_UNITS_EXCEED_ORDER": 422,
    "ERR_SEVERE_NO_TOUCHUP": 409,
    "ERR_TOUCHUP_LIMIT_REACHED": 409,
    "ERR_LOYALTY_PROGRAM_MISMATCH": 422,
    # Business fiscal / capacity
    "ERR_DEPOSIT_REQUIRED": 402,
    "ERR_INSUFFICIENT_LOT_UNITS": 409,
}
