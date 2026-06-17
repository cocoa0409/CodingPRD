"""Error catalog and ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (id -> http status) from PRD §5 / scaffold §1.6
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_DUE_DATE_INFEASIBLE": 422,
    "ERR_PRODUCT_INACTIVE": 409,
    "ERR_PROOF_NOT_APPROVED": 409,
    "ERR_PROMO_INVALID": 409,
    "ERR_PROMO_MIN_NOT_MET": 422,
    "ERR_COMPONENT_SHORTAGE": 409,
    "ERR_DEPOSIT_REQUIRED": 409,
    "ERR_BALANCE_DUE": 409,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
    "ERR_SHIP_WEIGHT_REQUIRED": 422,
    "ERR_DUPLICATE_VALUE": 409,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
