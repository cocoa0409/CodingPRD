"""Error catalog — error_id -> HTTP status, and the ApiError exception.

Status codes come from PRD §5 / SCAFFOLD §1.6 errors table.
"""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = (http_status if http_status is not None
                            else ERROR_STATUS.get(error_id, 400))


# error_id -> HTTP status (PRD §5).
ERROR_STATUS = {
    "ERR_INVALID_REQUEST": 400,
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_WINDOW_OVERLAP": 409,
    "ERR_TRAVEL_BUFFER_CONFLICT": 409,
    "ERR_CUSTOMER_DOUBLE_BOOKED": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_VALIDATION": 422,
    "ERR_PRO_NOT_CLEARED": 422,
    "ERR_LICENSE_REQUIRED": 422,
    "ERR_SKILL_TAG_MISMATCH": 422,
    "ERR_INSTANT_QUOTE_INELIGIBLE": 422,
    "ERR_ZIP_MISMATCH": 422,
    "ERR_VISIT_OUTSIDE_WINDOW": 422,
    "ERR_WARRANTY_EXPIRED": 422,
    "ERR_PARTIAL_PAYMENT": 422,
    "ERR_REFUND_EXCEEDS_PAID": 422,
    "ERR_PRICING_MODEL_MISMATCH": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, message)
