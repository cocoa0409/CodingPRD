"""Error catalog and the ApiError exception carrying error_id, message, http_status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id -> http_status), straight from PRD §5 / scaffold §1.6
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ACCOUNT_FROZEN": 409,
    "ERR_SELF_TRANSFER": 422,
    "ERR_VERIFICATION_TOKEN_INVALID": 422,
    "ERR_FUNDING_SOURCE_NOT_VERIFIED": 422,
    "ERR_DISPUTE_WINDOW_CLOSED": 422,
    "ERR_DAILY_LIMIT_EXCEEDED": 422,
    "ERR_WEEKLY_LIMIT_EXCEEDED": 422,
    "ERR_INSUFFICIENT_FUNDS": 422,
    "ERR_STALE_ACCOUNT_VERSION": 412,
    "ERR_SPLIT_PARTICIPANT_INVALID": 422,
    "ERR_FUNDING_SOURCE_IN_USE": 409,
    "ERR_VERIFICATION_ALREADY_PENDING": 409,
    "ERR_INVALID_REQUEST": 400,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
