"""Error IDs and HTTP status mapping (PRD §5).

Registers the mapping with the framework so validate_error() can auto-check
HTTP status codes.
"""
from enum import Enum
from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_STALE_TABLE_VERSION = "ERR_STALE_TABLE_VERSION"
    ERR_CAPACITY_EXCEEDED = "ERR_CAPACITY_EXCEEDED"
    ERR_ITEM_86 = "ERR_ITEM_86"
    ERR_EMPTY_COURSE = "ERR_EMPTY_COURSE"
    ERR_COMP_CAP_EXCEEDED = "ERR_COMP_CAP_EXCEEDED"
    ERR_UNDERPAID = "ERR_UNDERPAID"
    ERR_TABLE_DOUBLE_BOOKED = "ERR_TABLE_DOUBLE_BOOKED"
    ERR_SHIFT_OVERLAP = "ERR_SHIFT_OVERLAP"
    ERR_INVALID_SPLIT = "ERR_INVALID_SPLIT"
    ERR_POOL_EMPTY = "ERR_POOL_EMPTY"


HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_REQUEST: 422,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_STALE_TABLE_VERSION: 412,
    ApiErrorId.ERR_CAPACITY_EXCEEDED: 409,
    ApiErrorId.ERR_ITEM_86: 409,
    ApiErrorId.ERR_EMPTY_COURSE: 409,
    ApiErrorId.ERR_COMP_CAP_EXCEEDED: 409,
    ApiErrorId.ERR_UNDERPAID: 409,
    ApiErrorId.ERR_TABLE_DOUBLE_BOOKED: 409,
    ApiErrorId.ERR_SHIFT_OVERLAP: 409,
    ApiErrorId.ERR_INVALID_SPLIT: 422,
    ApiErrorId.ERR_POOL_EMPTY: 409,
}

# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map({k.value: v for k, v in HTTP_STATUS_CODES.items()})
