"""Error IDs and HTTP status mapping (PRD §5).

After defining the mapping, it is registered with the framework so that
validate_error() can cross-check HTTP status codes automatically.
"""
from enum import Enum
from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
    ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_CROSS_REFERENCE_MISMATCH = "ERR_CROSS_REFERENCE_MISMATCH"
    ERR_RATE_PLAN_NOT_QUOTABLE = "ERR_RATE_PLAN_NOT_QUOTABLE"
    ERR_INVALID_INTERVAL = "ERR_INVALID_INTERVAL"
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_CUSTOMER_SUSPENDED = "ERR_CUSTOMER_SUSPENDED"
    ERR_IN_OUT_NOT_ALLOWED = "ERR_IN_OUT_NOT_ALLOWED"
    ERR_STALE_LOT_VERSION = "ERR_STALE_LOT_VERSION"
    ERR_STALE_SHUTTLE_VERSION = "ERR_STALE_SHUTTLE_VERSION"
    ERR_NO_STALL_AVAILABLE = "ERR_NO_STALL_AVAILABLE"
    ERR_SHUTTLE_FULL = "ERR_SHUTTLE_FULL"
    ERR_VALIDATION = "ERR_VALIDATION"


HTTP_STATUS_CODES: dict[str, int] = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN_ROLE: 403,
    ApiErrorId.ERR_NOT_RESOURCE_OWNER: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_CROSS_REFERENCE_MISMATCH: 422,
    ApiErrorId.ERR_RATE_PLAN_NOT_QUOTABLE: 422,
    ApiErrorId.ERR_INVALID_INTERVAL: 422,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_CUSTOMER_SUSPENDED: 409,
    ApiErrorId.ERR_IN_OUT_NOT_ALLOWED: 409,
    ApiErrorId.ERR_STALE_LOT_VERSION: 412,
    ApiErrorId.ERR_STALE_SHUTTLE_VERSION: 412,
    ApiErrorId.ERR_NO_STALL_AVAILABLE: 409,
    ApiErrorId.ERR_SHUTTLE_FULL: 409,
    ApiErrorId.ERR_VALIDATION: 400,
}

# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map({k.value: v for k, v in HTTP_STATUS_CODES.items()})
