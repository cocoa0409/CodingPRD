"""Error classes and error-ID/HTTP-status catalog (PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Catalog: error_id -> http_status (PRD §5 / SCAFFOLD §1.6)
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_STALE_DEAL_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_WRONG_SIDE": 409,
    "ERR_LISTING_NOT_NEGOTIABLE": 409,
    "ERR_REQUIREMENT_NOT_ACTIVE": 409,
    "ERR_SPACE_NOT_AVAILABLE": 409,
    "ERR_TOUR_WINDOW_CONFLICT": 409,
    "ERR_BROKER_DOUBLE_BOOKED": 409,
    "ERR_TOUR_NOT_STARTED": 409,
    "ERR_TOUR_NOT_ENDED": 409,
    "ERR_LISTING_HAS_LIVE_DEAL": 409,
    "ERR_REQUIREMENT_HAS_LIVE_DEAL": 409,
    "ERR_BROKER_SUSPENDED": 409,
    "ERR_VALIDATION": 400,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
