"""Error catalog and ApiError exception per PRD §5."""
from __future__ import annotations

ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_FORBIDDEN_OWNERSHIP = "ERR_FORBIDDEN_OWNERSHIP"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_WINDOW_TIMING = "ERR_WINDOW_TIMING"
ERR_DISTRICT_ARCHIVED = "ERR_DISTRICT_ARCHIVED"
ERR_DUPLICATE_CHOICE = "ERR_DUPLICATE_CHOICE"
ERR_GRADE_OUT_OF_RANGE = "ERR_GRADE_OUT_OF_RANGE"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_DISTRICT_DATA_INVALID = "ERR_DISTRICT_DATA_INVALID"
ERR_ZONE_UNKNOWN = "ERR_ZONE_UNKNOWN"

HTTP_FOR = {
    ERR_UNAUTHENTICATED: 401,
    ERR_FORBIDDEN: 403,
    ERR_FORBIDDEN_OWNERSHIP: 403,
    ERR_NOT_FOUND: 404,
    ERR_INVALID_STATE: 409,
    ERR_WINDOW_TIMING: 422,
    ERR_DISTRICT_ARCHIVED: 422,
    ERR_DUPLICATE_CHOICE: 409,
    ERR_GRADE_OUT_OF_RANGE: 422,
    ERR_STALE_VERSION: 412,
    ERR_INVALID_REQUEST: 400,
    ERR_DISTRICT_DATA_INVALID: 422,
    ERR_ZONE_UNKNOWN: 422,
}


class ApiError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int | None = None):
        self.error_id = error_id
        self.message = message
        self.http_status = http_status if http_status is not None else HTTP_FOR.get(error_id, 400)
        super().__init__(message)


def raise_err(error_id: str, message: str, http_status: int | None = None):
    raise ApiError(error_id, message, http_status)
