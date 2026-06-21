"""Error IDs and HTTP status mapping (PRD Section 5)."""
from enum import Enum
from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
    ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_FK_INVALID = "ERR_FK_INVALID"
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_WITHIN_WAITING_PERIOD = "ERR_WITHIN_WAITING_PERIOD"
    ERR_PRE_EXISTING_EXCLUDED = "ERR_PRE_EXISTING_EXCLUDED"
    ERR_POLICY_YEAR_CLOSED = "ERR_POLICY_YEAR_CLOSED"
    ERR_CLAIM_NOT_READY = "ERR_CLAIM_NOT_READY"
    ERR_WELLNESS_RIDER_REQUIRED = "ERR_WELLNESS_RIDER_REQUIRED"
    ERR_STALE_POLICY_YEAR_VERSION = "ERR_STALE_POLICY_YEAR_VERSION"
    ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
    # Sentinel denial_reason stored on a reversed claim; never returned as an HTTP error.
    ERR_CLAIM_REVERSED = "ERR_CLAIM_REVERSED"


# Only error_ids that surface as HTTP error responses are registered.
# ERR_CLAIM_REVERSED is a stored denial_reason sentinel, not an HTTP error.
HTTP_STATUS_CODES: dict[str, int] = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN_ROLE: 403,
    ApiErrorId.ERR_NOT_RESOURCE_OWNER: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_FK_INVALID: 422,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_WITHIN_WAITING_PERIOD: 422,
    ApiErrorId.ERR_PRE_EXISTING_EXCLUDED: 422,
    ApiErrorId.ERR_POLICY_YEAR_CLOSED: 422,
    ApiErrorId.ERR_CLAIM_NOT_READY: 422,
    ApiErrorId.ERR_WELLNESS_RIDER_REQUIRED: 422,
    ApiErrorId.ERR_STALE_POLICY_YEAR_VERSION: 412,
    ApiErrorId.ERR_INVALID_REQUEST: 400,
}

set_error_http_status_map({k.value: v for k, v in HTTP_STATUS_CODES.items()})
