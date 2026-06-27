"""Error IDs and HTTP status mapping (PRD Section 5).

After defining the mapping, register it with the framework so validate_error()
can cross-check HTTP status codes automatically.
"""
from enum import Enum
from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_STALE_VERSION = "ERR_STALE_VERSION"
    ERR_WAIVER_REQUIRED = "ERR_WAIVER_REQUIRED"
    ERR_CERT_PREREQUISITE_NOT_MET = "ERR_CERT_PREREQUISITE_NOT_MET"
    ERR_INSTRUCTOR_CONFLICT = "ERR_INSTRUCTOR_CONFLICT"
    ERR_BOAT_CONFLICT = "ERR_BOAT_CONFLICT"
    ERR_CAPACITY_EXCEEDED = "ERR_CAPACITY_EXCEEDED"
    ERR_DUPLICATE_BOOKING = "ERR_DUPLICATE_BOOKING"


HTTP_STATUS_CODES: dict[str, int] = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_REQUEST: 400,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_STALE_VERSION: 412,
    ApiErrorId.ERR_WAIVER_REQUIRED: 422,
    ApiErrorId.ERR_CERT_PREREQUISITE_NOT_MET: 422,
    ApiErrorId.ERR_INSTRUCTOR_CONFLICT: 409,
    ApiErrorId.ERR_BOAT_CONFLICT: 409,
    ApiErrorId.ERR_CAPACITY_EXCEEDED: 409,
    ApiErrorId.ERR_DUPLICATE_BOOKING: 409,
}

# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map({k.value: v for k, v in HTTP_STATUS_CODES.items()})
