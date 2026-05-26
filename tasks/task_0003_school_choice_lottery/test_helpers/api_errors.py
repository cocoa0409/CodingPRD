"""Error IDs and HTTP status mapping (PRD §5)."""
from enum import Enum
from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
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


HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHENTICATED.value: 401,
    ApiErrorId.ERR_FORBIDDEN.value: 403,
    ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value: 403,
    ApiErrorId.ERR_NOT_FOUND.value: 404,
    ApiErrorId.ERR_INVALID_STATE.value: 409,
    ApiErrorId.ERR_WINDOW_TIMING.value: 422,
    ApiErrorId.ERR_DISTRICT_ARCHIVED.value: 422,
    ApiErrorId.ERR_DUPLICATE_CHOICE.value: 409,
    ApiErrorId.ERR_GRADE_OUT_OF_RANGE.value: 422,
    ApiErrorId.ERR_STALE_VERSION.value: 412,
    ApiErrorId.ERR_INVALID_REQUEST.value: 400,
    ApiErrorId.ERR_DISTRICT_DATA_INVALID.value: 422,
    ApiErrorId.ERR_ZONE_UNKNOWN.value: 422,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(HTTP_STATUS_CODES)
