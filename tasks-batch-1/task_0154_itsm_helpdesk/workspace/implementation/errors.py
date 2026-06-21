"""Error classes and the error catalog (PRD §5)."""


class ApiError(Exception):
    """Carries the machine-readable error_id, HTTP status, and message."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog: error_id -> http_status (PRD §5 / SCAFFOLD §1.6) ---
ERROR_STATUS = {
    "ERR_VALIDATION": 400,
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_SOD_VIOLATION": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_CHANGE_GATING_RESOLUTION": 409,
    "ERR_PROBLEM_HAS_OPEN_TICKETS": 409,
    "ERR_ASSET_HAS_OPEN_INCIDENTS": 409,
    "ERR_REOPEN_WINDOW_CLOSED": 409,
    "ERR_CSAT_WINDOW_CLOSED": 409,
    "ERR_DUPLICATE_SURVEY": 409,
    "ERR_DUPLICATE_VOTE": 409,
    "ERR_DUPLICATE_ASSET_TAG": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_FIELD_VALUE": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
