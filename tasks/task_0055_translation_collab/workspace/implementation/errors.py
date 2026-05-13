"""Custom error classes and error_id catalog."""


class ApiError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        self.error_id = error_id
        self.message = message
        self.http_status = http_status
        super().__init__(message)


# Error catalog: id -> http_status
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_INVALID_SEGMENT_STATE": 409,
    "ERR_INVALID_ASSIGNMENT_STATE": 409,
    "ERR_ASSIGNMENT_ALREADY_TAKEN": 409,
    "ERR_PROJECT_NOT_READY": 409,
    "ERR_TEST_TRANSLATION_REQUIRED": 422,
    "ERR_TRANSLATOR_PROFILE_MISMATCH": 422,
    "ERR_ACCEPT_WINDOW_EXPIRED": 409,
    "ERR_SEGMENT_ALREADY_ASSIGNED": 409,
    "ERR_PACKAGE_SIZE_EXCEEDED": 422,
    "ERR_TRANSLATOR_OVERLOADED": 422,
    "ERR_TERMINOLOGY_CONFLICT": 409,
    "ERR_REPETITION_PRICE_TOO_LOW": 422,
    "ERR_INVALID_PRICE": 422,
    "ERR_DEADLINE_NOT_IN_FUTURE": 422,
    "ERR_SAME_SOURCE_TARGET": 422,
    "ERR_EMPTY_PROJECT": 422,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_VALIDATION_FAILED": 422,
    "ERR_NO_ELIGIBLE_TRANSLATOR": 409,
    "ERR_QUALITY_SCORE_ALREADY_FINALIZED": 409,
    "ERR_TERMINOLOGY_RESOLVE_REQUIRES_LOSER": 422,
}


def err(error_id: str, message: str = "") -> ApiError:
    return ApiError(error_id, message or error_id, ERROR_HTTP[error_id])
