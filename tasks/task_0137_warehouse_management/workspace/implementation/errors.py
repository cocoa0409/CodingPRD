"""Error catalogue and the ApiError exception carried through the app."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status for each error id (PRD §5 / scaffold §1.6).
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_WAVE_VERSION": 412,
    "ERR_STALE_LPN_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CROSS_ENTITY_STATE": 409,
    "ERR_DUPLICATE_CODE": 409,
    "ERR_LOCATION_CAPACITY": 409,
    "ERR_PICKFACE_TAKEN": 409,
    "ERR_REPLEN_NOT_NEEDED": 409,
    "ERR_INSUFFICIENT_AVAILABLE": 409,
    "ERR_ASN_LINES_OPEN": 409,
    "ERR_NO_PUTAWAY_LOCATION": 409,
    "ERR_NO_REPLEN_SOURCE": 409,
    "ERR_VALIDATION_LIGHT_REQUIRED": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)
