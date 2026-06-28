"""Error classes and error ID -> HTTP status mapping (from PRD §5 / scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http status
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_ITEM_VERSION": 412,
    "ERR_ALTERATION_NOTE_REQUIRED": 422,
    "ERR_COUNTERFEIT_NOT_ENCAPSULATABLE": 422,
    "ERR_SUBGRADE_OUT_OF_RANGE": 422,
    "ERR_WEIGHTS_NOT_NORMALIZED": 422,
    "ERR_ACTIVE_SLAB_EXISTS": 409,
    "ERR_SUBMISSION_ALREADY_SHIPPED": 409,
    "ERR_DECLARED_VALUE_EXCEEDS_TIER": 422,
    "ERR_EMPTY_SUBMISSION": 422,
    "ERR_SUBMISSION_FROZEN": 409,
    "ERR_INVALID_REQUEST": 400,
    "ERR_VALIDATION": 422,
    "ERR_DUPLICATE_INTAKE": 409,
    "ERR_PAGINATION_INVALID": 400,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
