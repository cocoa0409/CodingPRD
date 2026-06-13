"""Error IDs and HTTP status mapping (PRD §5 Error Code Catalogue).

After defining the mapping it is registered with the framework so validate_error()
auto-checks HTTP status codes.
"""
from enum import Enum
from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
    ERR_DUPLICATE = "ERR_DUPLICATE"
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_PRODUCT_MISMATCH = "ERR_PRODUCT_MISMATCH"
    ERR_STALE_ROAST = "ERR_STALE_ROAST"
    ERR_RELEASE_NOT_DUE = "ERR_RELEASE_NOT_DUE"
    ERR_INSUFFICIENT_GREEN = "ERR_INSUFFICIENT_GREEN"
    ERR_INSUFFICIENT_ROASTED = "ERR_INSUFFICIENT_ROASTED"
    ERR_WEIGHT_GAIN = "ERR_WEIGHT_GAIN"
    ERR_CREDIT_LIMIT_EXCEEDED = "ERR_CREDIT_LIMIT_EXCEEDED"
    ERR_OVERPAYMENT = "ERR_OVERPAYMENT"
    ERR_STALE_VERSION = "ERR_STALE_VERSION"


HTTP_STATUS_CODES: dict[str, int] = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_REQUEST: 422,
    ApiErrorId.ERR_DUPLICATE: 409,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_PRODUCT_MISMATCH: 409,
    ApiErrorId.ERR_STALE_ROAST: 409,
    ApiErrorId.ERR_RELEASE_NOT_DUE: 409,
    ApiErrorId.ERR_INSUFFICIENT_GREEN: 409,
    ApiErrorId.ERR_INSUFFICIENT_ROASTED: 409,
    ApiErrorId.ERR_WEIGHT_GAIN: 409,
    ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED: 409,
    ApiErrorId.ERR_OVERPAYMENT: 409,
    ApiErrorId.ERR_STALE_VERSION: 412,
}

# Register with framework so validate_error() auto-checks HTTP status
set_error_http_status_map(HTTP_STATUS_CODES)
