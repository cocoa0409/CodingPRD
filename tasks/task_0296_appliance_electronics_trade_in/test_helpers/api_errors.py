"""Error IDs and HTTP status mapping (PRD §5).

Registers the mapping with the framework so validate_error() auto-checks the
HTTP status code for each error_id.
"""
from enum import Enum
from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_NOT_OWNER = "ERR_NOT_OWNER"
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_FK_NOT_FOUND = "ERR_FK_NOT_FOUND"
    ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_STALE_VERSION = "ERR_STALE_VERSION"
    ERR_MODEL_RETIRED = "ERR_MODEL_RETIRED"
    ERR_PROMO_INVALID = "ERR_PROMO_INVALID"
    ERR_UNKNOWN_DEFECT = "ERR_UNKNOWN_DEFECT"
    ERR_QUOTE_EXPIRED = "ERR_QUOTE_EXPIRED"
    ERR_DATA_WIPE_REQUIRED = "ERR_DATA_WIPE_REQUIRED"
    ERR_DUPLICATE = "ERR_DUPLICATE"
    ERR_INVALID_MULTIPLIERS = "ERR_INVALID_MULTIPLIERS"
    ERR_PROMO_WINDOW_OVERLAP = "ERR_PROMO_WINDOW_OVERLAP"
    ERR_SLOT_OVERLAP = "ERR_SLOT_OVERLAP"


HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_OWNER: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_FK_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_REQUEST: 400,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_STALE_VERSION: 412,
    ApiErrorId.ERR_MODEL_RETIRED: 409,
    ApiErrorId.ERR_PROMO_INVALID: 409,
    ApiErrorId.ERR_UNKNOWN_DEFECT: 422,
    ApiErrorId.ERR_QUOTE_EXPIRED: 409,
    ApiErrorId.ERR_DATA_WIPE_REQUIRED: 409,
    ApiErrorId.ERR_DUPLICATE: 409,
    ApiErrorId.ERR_INVALID_MULTIPLIERS: 422,
    ApiErrorId.ERR_PROMO_WINDOW_OVERLAP: 409,
    ApiErrorId.ERR_SLOT_OVERLAP: 409,
}

# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map({k.value: v for k, v in HTTP_STATUS_CODES.items()})
