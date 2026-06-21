"""Error IDs and HTTP status mapping (PRD §5).

Registers the mapping with the framework so validate_error() can auto-check the
HTTP status code that accompanies each error_id.
"""
from enum import Enum
from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
    ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_WEEK_CLOSED = "ERR_WEEK_CLOSED"
    ERR_TAP_WEEK_MISMATCH = "ERR_TAP_WEEK_MISMATCH"
    ERR_BAD_VERIFICATION_TOKEN = "ERR_BAD_VERIFICATION_TOKEN"
    ERR_CARD_EXPIRED = "ERR_CARD_EXPIRED"
    ERR_DUPLICATE_ALLOCATION = "ERR_DUPLICATE_ALLOCATION"
    ERR_FSA_CAP_EXCEEDED = "ERR_FSA_CAP_EXCEEDED"
    ERR_STALE_RIDER_VERSION = "ERR_STALE_RIDER_VERSION"
    ERR_INSUFFICIENT_FUNDS = "ERR_INSUFFICIENT_FUNDS"


HTTP_STATUS_CODES: dict[str, int] = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN_ROLE: 403,
    ApiErrorId.ERR_NOT_RESOURCE_OWNER: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_REQUEST: 422,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_WEEK_CLOSED: 409,
    ApiErrorId.ERR_TAP_WEEK_MISMATCH: 422,
    ApiErrorId.ERR_BAD_VERIFICATION_TOKEN: 422,
    ApiErrorId.ERR_CARD_EXPIRED: 409,
    ApiErrorId.ERR_DUPLICATE_ALLOCATION: 409,
    ApiErrorId.ERR_FSA_CAP_EXCEEDED: 422,
    ApiErrorId.ERR_STALE_RIDER_VERSION: 412,
    ApiErrorId.ERR_INSUFFICIENT_FUNDS: 402,
}

# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map({k.value: v for k, v in HTTP_STATUS_CODES.items()})
