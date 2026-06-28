"""Error classes and error-id -> HTTP-status catalogue (PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status if http_status is not None else ERROR_STATUS[error_id]


# error_id -> HTTP status code (PRD §5 catalogue)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_NO_SCHEDULED_ITEMS": 409,
    "ERR_NAMED_PERIL_REQUIRES_PERILS": 409,
    "ERR_APPRAISAL_REQUIRED": 409,
    "ERR_POLICY_NOT_ACTIVE": 409,
    "ERR_PERIL_NOT_COVERED": 409,
    "ERR_WORLDWIDE_NOT_COVERED": 409,
    "ERR_ITEM_LOCKED_BY_CLAIM": 409,
    "ERR_NO_OP_ENDORSEMENT": 422,
    "ERR_INFO_REQUEST_LIMIT": 409,
    "ERR_SHOP_SUSPENDED": 409,
    "ERR_REPAIR_EXCEEDS_AUTH": 409,
    "ERR_PREMIUM_UNDERPAID": 409,
    "ERR_POLICY_NOT_BILLABLE": 409,
    "ERR_PARTIAL_REQUIRES_REPAIR": 409,
    "ERR_OPEN_CLAIM_BLOCKS_CANCEL": 409,
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, message)
