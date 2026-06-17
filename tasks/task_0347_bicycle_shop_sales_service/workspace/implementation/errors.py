"""Error classes and error ID -> HTTP status mapping (from PRD §5 / scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or error_id


# Maps every error_id to its HTTP status code (PRD §5 Error Code Catalogue).
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_EMAIL": 409,
    "ERR_NOT_PURCHASED": 409,
    "ERR_WARRANTY_NOT_COVERED": 409,
    "ERR_FRAME_NOT_BIKE": 409,
    "ERR_BUILD_NOT_READY": 409,
    "ERR_RECALL_BLOCK": 409,
    "ERR_INSUFFICIENT_STOCK": 409,
    "ERR_NOT_FULLY_PAID": 409,
    "ERR_DEPOSIT_SHORT": 409,
    "ERR_LAYAWAY_NOT_PAID_OFF": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_TARGET_NOT_PAYABLE": 409,
    "ERR_ALREADY_ACKNOWLEDGED": 409,
    "ERR_BAY_DOUBLE_BOOKED": 409,
    "ERR_INVALID_PAGINATION": 400,
}
