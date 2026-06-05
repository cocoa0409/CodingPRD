"""Error catalog and the ApiError exception (PRD §5 / SCAFFOLD §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> http status
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_LICENSE_NOT_ACTIVE": 403,
    "ERR_LICENSE_TYPE_MISMATCH": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_LAB_HOLD_ACTIVE": 409,
    "ERR_SOURCE_DISCRIMINATOR_MISMATCH": 422,
    "ERR_DUPLICATE_TAG": 409,
    "ERR_INSUFFICIENT_QUANTITY": 409,
    "ERR_MANIFEST_OVERLAP": 409,
    "ERR_SALE_WINDOW_OVERLAP": 409,
    "ERR_DAILY_LIMIT_EXCEEDED": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PARENT_STATE": 409,
    "ERR_WEIGHT_RANGE": 422,
    "ERR_AGE_VERIFICATION_FAILED": 422,
    "ERR_PARTIAL_DESTROY_NOT_TERMINAL": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
