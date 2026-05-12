"""Error classes and the canonical error catalog."""


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Canonical error catalog: error_id -> http_status
ERROR_CATALOG = {
    # Auth
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    # Request
    "ERR_INVALID_REQUEST": 400,
    "ERR_IDEMPOTENCY_KEY_REUSED": 409,
    "ERR_VERSION_CONFLICT": 409,
    # Not found
    "ERR_NURSE_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_SERVICE_ITEM_NOT_FOUND": 404,
    "ERR_DISPATCH_NOT_FOUND": 404,
    "ERR_WASTE_NOT_FOUND": 404,
    "ERR_COMPLAINT_NOT_FOUND": 404,
    "ERR_PACKAGE_NOT_FOUND": 404,
    # State
    "ERR_INVALID_STATE": 409,
    "ERR_DISPATCH_ALREADY_TAKEN": 409,
    "ERR_DISPATCH_WINDOW_EXPIRED": 409,
    "ERR_WASTE_NOT_ARCHIVED": 409,
    "ERR_PAYOUT_BATCH_ALREADY_BUILDING": 409,
    # Referential
    "ERR_RESOURCE_LINK_INVALID": 422,
    # Safety / business
    "ERR_MEDICAL_DOC_REQUIRED": 422,
    "ERR_NURSE_NOT_CERTIFIED": 422,
    "ERR_CHECKIN_OUT_OF_RANGE": 422,
    "ERR_FACE_VERIFICATION_FAILED": 422,
    "ERR_CHECKLIST_INCOMPLETE": 422,
    "ERR_NO_AVAILABLE_NURSE": 422,
    # Fiscal / refund
    "ERR_REFUND_WINDOW_EXPIRED": 422,
    "ERR_COMPENSATION_EXCEEDS_FEE": 422,
    "ERR_INSUFFICIENT_PACKAGE_CREDIT": 422,
}


def err(error_id: str, message: str = "") -> APIError:
    return APIError(error_id, message or error_id, ERROR_CATALOG[error_id])
