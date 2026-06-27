"""Custom exception carrying error_id, message, and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Error catalog (id -> http status). Mirrors PRD §5 / SCAFFOLD §1.6 exactly.
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    # auth
    "ERR_MISSING_USER_CONTEXT": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_OWNER": 403,
    # request validation
    "ERR_INVALID_REQUEST": 422,
    # not found
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_STUDENT_NOT_FOUND": 404,
    "ERR_PHOTO_NOT_FOUND": 404,
    "ERR_PACKAGE_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_LINE_NOT_FOUND": 404,
    "ERR_RETOUCH_NOT_FOUND": 404,
    "ERR_SHIPMENT_NOT_FOUND": 404,
    "ERR_BACKDROP_NOT_FOUND": 404,
    "ERR_PHOTOGRAPHER_NOT_FOUND": 404,
    "ERR_SLOT_NOT_FOUND": 404,
    # session posture / lifecycle
    "ERR_EMPTY_ROSTER": 409,
    "ERR_EMPTY_CATALOG": 409,
    "ERR_CAPTURE_INCOMPLETE": 409,
    "ERR_RETAKE_PENDING": 409,
    "ERR_OPEN_ORDERS_EXIST": 409,
    "ERR_UNSHIPPED_ORDERS": 409,
    "ERR_PAID_ORDERS_EXIST": 409,
    "ERR_SESSION_NOT_CAPTURING": 409,
    "ERR_SESSION_NOT_ORDERING": 409,
    "ERR_SESSION_NOT_GALLERY": 409,
    "ERR_SESSION_NOT_RETAKEABLE": 409,
    "ERR_INVALID_SESSION_TRANSITION": 409,
    # entity state
    "ERR_STUDENT_ALREADY_PHOTOGRAPHED": 409,
    "ERR_PHOTO_NOT_RETAKEABLE": 409,
    "ERR_PHOTO_NOT_APPROVABLE": 409,
    "ERR_ORDER_NOT_SUBMITTED": 409,
    "ERR_ORDER_NOT_PAID": 409,
    "ERR_ORDER_NOT_CANCELLABLE": 409,
    "ERR_ORDER_NOT_CART": 409,
    "ERR_EMPTY_ORDER": 409,
    "ERR_RETOUCH_NOT_APPROVED": 409,
    "ERR_RETOUCH_NOT_REQUESTED": 409,
    "ERR_RETOUCH_NOT_CANCELLABLE": 409,
    "ERR_SHIPMENT_NOT_DISPATCHED": 409,
    "ERR_SHIPMENT_NOT_VOIDABLE": 409,
    "ERR_TRACKING_REQUIRED": 409,
    "ERR_SLOT_NOT_SCHEDULED": 409,
    "ERR_SLOT_NOT_CANCELLABLE": 409,
    # business gates
    "ERR_NO_MATCH_CANDIDATE": 422,
    "ERR_GALLERY_ACCESS_DENIED": 403,
    "ERR_INSUFFICIENT_RETOUCH_CREDIT": 402,
    "ERR_BACKDROP_DOUBLE_BOOKED": 409,
    "ERR_PHOTOGRAPHER_DOUBLE_BOOKED": 409,
    # concurrency
    "ERR_STALE_SESSION_VERSION": 412,
}


def err(error_id, message=None):
    """Construct an ApiError from the catalog, defaulting the HTTP status."""
    return ApiError(error_id, ERROR_STATUS.get(error_id, 400), message)
