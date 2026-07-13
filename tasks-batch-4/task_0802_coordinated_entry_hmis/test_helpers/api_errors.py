"""Error IDs and HTTP status mapping (PRD §5).

After defining the mapping, register it with the framework so validate_error()
auto-checks the HTTP status code for each error_id.
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
    ERR_ASSESSMENT_REQUIRED = "ERR_ASSESSMENT_REQUIRED"
    ERR_CONSENT_REQUIRED = "ERR_CONSENT_REQUIRED"
    ERR_MERGE_INVALID = "ERR_MERGE_INVALID"
    ERR_CLIENT_DOUBLE_BOOKED = "ERR_CLIENT_DOUBLE_BOOKED"
    ERR_CASELOAD_FULL = "ERR_CASELOAD_FULL"
    ERR_DUPLICATE_BED_LABEL = "ERR_DUPLICATE_BED_LABEL"
    ERR_DUPLICATE_WAITLIST = "ERR_DUPLICATE_WAITLIST"
    ERR_SHELTER_AT_CAPACITY = "ERR_SHELTER_AT_CAPACITY"
    ERR_POOL_INELIGIBLE = "ERR_POOL_INELIGIBLE"
    ERR_ALREADY_EXITED = "ERR_ALREADY_EXITED"


HTTP_STATUS_CODES: dict[str, int] = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_REQUEST: 400,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_STALE_VERSION: 412,
    ApiErrorId.ERR_ASSESSMENT_REQUIRED: 409,
    ApiErrorId.ERR_CONSENT_REQUIRED: 409,
    ApiErrorId.ERR_MERGE_INVALID: 409,
    ApiErrorId.ERR_CLIENT_DOUBLE_BOOKED: 409,
    ApiErrorId.ERR_CASELOAD_FULL: 409,
    ApiErrorId.ERR_DUPLICATE_BED_LABEL: 409,
    ApiErrorId.ERR_DUPLICATE_WAITLIST: 409,
    ApiErrorId.ERR_SHELTER_AT_CAPACITY: 409,
    ApiErrorId.ERR_POOL_INELIGIBLE: 409,
    ApiErrorId.ERR_ALREADY_EXITED: 409,
}

# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map({k.value: v for k, v in HTTP_STATUS_CODES.items()})
