"""Error catalog and the ApiError exception (PRD §5, scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http_status (PRD §5 / scaffold §1.6)
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_PERMIT_REQUIRED": 409,
    "ERR_TECH_NOT_CERTIFIED": 409,
    "ERR_RELOCATION_DISTANCE": 422,
    "ERR_ENTRY_POINT_MISMATCH": 409,
    "ERR_TECH_WINDOW_CONFLICT": 409,
    "ERR_VISIT_OVERLAP": 409,
    "ERR_INVALID_WINDOW": 422,
    "ERR_EMPTY_SET": 409,
    "ERR_KIT_EXHAUSTED": 409,
    "ERR_INVALID_REQUEST": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)
