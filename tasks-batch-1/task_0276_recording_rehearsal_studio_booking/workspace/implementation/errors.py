"""Error classes and error-id constants (PRD §5 error catalogue)."""


class ApiError(Exception):
    """Carries an error_id, message, and HTTP status to the response layer."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status per error id (PRD §5 / scaffold §1.6)
ERR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_TIME_RANGE": 422,
    "ERR_ENGINEER_REQUIRED": 422,
    "ERR_ROOM_UNAVAILABLE": 409,
    "ERR_LOCKOUT_CONFLICT": 409,
    "ERR_GEAR_UNAVAILABLE": 409,
    "ERR_ENGINEER_UNAVAILABLE": 409,
    "ERR_DEPOSIT_MISMATCH": 422,
    "ERR_BALANCE_MISMATCH": 422,
    "ERR_DUPLICATE_EMAIL": 409,
    "ERR_INVALID_REQUEST": 400,
    "ERR_VALIDATION": 422,
    "ERR_SESSION_NOT_DELIVERABLE": 409,
    "ERR_CANCEL_TOO_LATE": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERR_STATUS[error_id], message)
