"""Error IDs and HTTP status mapping (PRD §5).

After defining the mapping it is registered with the framework so that
validate_error() can auto-check HTTP status codes.
"""
from enum import Enum
from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_VALIDATION = "ERR_VALIDATION"
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_UNIT_NOT_AVAILABLE = "ERR_UNIT_NOT_AVAILABLE"
    ERR_WINDOW_CONFLICT = "ERR_WINDOW_CONFLICT"
    ERR_SLOT_FULL = "ERR_SLOT_FULL"
    ERR_LESSON_REQUIRED = "ERR_LESSON_REQUIRED"
    ERR_CUSTOMER_SUSPENDED = "ERR_CUSTOMER_SUSPENDED"
    ERR_STALE_VERSION = "ERR_STALE_VERSION"
    ERR_ASSESSMENT_DISPUTED = "ERR_ASSESSMENT_DISPUTED"


HTTP_STATUS_CODES: dict[str, int] = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_UNAUTHORIZED: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_VALIDATION: 400,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_UNIT_NOT_AVAILABLE: 409,
    ApiErrorId.ERR_WINDOW_CONFLICT: 409,
    ApiErrorId.ERR_SLOT_FULL: 409,
    ApiErrorId.ERR_LESSON_REQUIRED: 422,
    ApiErrorId.ERR_CUSTOMER_SUSPENDED: 409,
    ApiErrorId.ERR_STALE_VERSION: 412,
    ApiErrorId.ERR_ASSESSMENT_DISPUTED: 409,
}

# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map({k.value: v for k, v in HTTP_STATUS_CODES.items()})
