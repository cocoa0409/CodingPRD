"""Error IDs and HTTP status mapping (PRD §5).

After defining the mapping, registers it with the framework so
`validate_error()` can cross-check HTTP status codes automatically.
"""
from enum import Enum

from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_STALE_VERSION = "ERR_STALE_VERSION"
    ERR_NOT_OWNER = "ERR_NOT_OWNER"
    ERR_DEFECT_NOT_COVERED = "ERR_DEFECT_NOT_COVERED"
    ERR_WARRANTY_EXPIRED = "ERR_WARRANTY_EXPIRED"
    ERR_REFUND_NOT_ELIGIBLE = "ERR_REFUND_NOT_ELIGIBLE"
    ERR_TIER_MISMATCH = "ERR_TIER_MISMATCH"
    ERR_DUPLICATE_SERIAL = "ERR_DUPLICATE_SERIAL"
    ERR_COVERAGE_EXHAUSTED = "ERR_COVERAGE_EXHAUSTED"
    ERR_COVERAGE_OVERLAP = "ERR_COVERAGE_OVERLAP"
    ERR_CLAIM_COOLDOWN = "ERR_CLAIM_COOLDOWN"
    ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"


HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_STALE_VERSION: 412,
    ApiErrorId.ERR_NOT_OWNER: 403,
    ApiErrorId.ERR_DEFECT_NOT_COVERED: 422,
    ApiErrorId.ERR_WARRANTY_EXPIRED: 422,
    ApiErrorId.ERR_REFUND_NOT_ELIGIBLE: 422,
    ApiErrorId.ERR_TIER_MISMATCH: 422,
    ApiErrorId.ERR_DUPLICATE_SERIAL: 409,
    ApiErrorId.ERR_COVERAGE_EXHAUSTED: 422,
    ApiErrorId.ERR_COVERAGE_OVERLAP: 409,
    ApiErrorId.ERR_CLAIM_COOLDOWN: 409,
    ApiErrorId.ERR_INVALID_REQUEST: 400,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(HTTP_STATUS_CODES)
