"""Error IDs and HTTP status mapping (PRD §5 error catalogue)."""
from enum import Enum

from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_STALE_VERSION = "ERR_STALE_VERSION"
    ERR_COMPLIANCE_FAILED = "ERR_COMPLIANCE_FAILED"
    ERR_DUPLICATE = "ERR_DUPLICATE"
    ERR_WINDOW_VIOLATION = "ERR_WINDOW_VIOLATION"
    ERR_REFERENTIAL = "ERR_REFERENTIAL"
    ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"


HTTP_STATUS_CODES: dict[str, int] = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_UNAUTHORIZED: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_STALE_VERSION: 412,
    ApiErrorId.ERR_COMPLIANCE_FAILED: 422,
    ApiErrorId.ERR_DUPLICATE: 409,
    ApiErrorId.ERR_WINDOW_VIOLATION: 422,
    ApiErrorId.ERR_REFERENTIAL: 422,
    ApiErrorId.ERR_INVALID_REQUEST: 400,
}

# Register with framework so validate_error() auto-checks HTTP status codes.
set_error_http_status_map(HTTP_STATUS_CODES)
