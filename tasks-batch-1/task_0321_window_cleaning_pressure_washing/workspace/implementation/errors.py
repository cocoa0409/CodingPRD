"""Error catalogue and the ApiError exception.

Error IDs and HTTP statuses are taken verbatim from SCAFFOLD.yaml §1.6 /
PRD.md §5. Do not invent IDs or statuses.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id -> http_status) — the single source of truth for status codes.
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENTIAL_MISMATCH": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_QUOTE_EXPIRED": 409,
    "ERR_AGREEMENT_NOT_ACTIVE": 409,
    "ERR_ROUTE_NOT_PLANNING": 409,
    "ERR_VISIT_NOT_COMPLETED": 409,
    "ERR_CREW_OFFLINE": 409,
    "ERR_CREW_SKILL_MISSING": 422,
    "ERR_BEFORE_PHOTO_REQUIRED": 422,
    "ERR_AFTER_PHOTO_REQUIRED": 422,
    "ERR_REGION_MISMATCH": 422,
    "ERR_DATE_MISMATCH": 422,
    "ERR_VISIT_WINDOW_OVERLAP": 409,
    "ERR_NO_WEATHER_HOLD": 409,
    "ERR_ROUTE_CAPACITY_EXCEEDED": 422,
    "ERR_DEPOSIT_NOT_MET": 422,
    "ERR_DUPLICATE_INVOICE": 409,
    "ERR_STALE_ROUTE_VERSION": 412,
    "ERR_OPEN_VISITS_EXIST": 409,
    "ERR_EMPTY_ROUTE": 422,
    "ERR_CREW_DOUBLE_BOOKED": 409,
    "ERR_INVALID_REQUEST": 400,
}


def err(error_id, message=None):
    """Build an ApiError, resolving its HTTP status from the catalogue."""
    return ApiError(error_id, ERROR_STATUS[error_id], message)
