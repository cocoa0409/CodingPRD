"""Error IDs and HTTP status mapping (PRD §5 Error Code Catalogue).

After defining the map, register it with the framework so validate_error()
auto-checks HTTP status codes.
"""
from enum import Enum
from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
    ERR_DUPLICATE_KEY = "ERR_DUPLICATE_KEY"
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_STALE_UNIT_VERSION = "ERR_STALE_UNIT_VERSION"
    ERR_UNIT_NOT_RESERVABLE = "ERR_UNIT_NOT_RESERVABLE"
    ERR_TRADEIN_NOT_OFFERED = "ERR_TRADEIN_NOT_OFFERED"
    ERR_RECALL_CANNOT_DENY = "ERR_RECALL_CANNOT_DENY"
    ERR_AUCTION_WINDOW = "ERR_AUCTION_WINDOW"
    ERR_BID_TOO_LOW = "ERR_BID_TOO_LOW"
    ERR_CURTAILMENT_SHORT = "ERR_CURTAILMENT_SHORT"
    ERR_PARTS_SHORTAGE = "ERR_PARTS_SHORTAGE"
    ERR_NO_MATCHING_UNIT = "ERR_NO_MATCHING_UNIT"


HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_REQUEST: 422,
    ApiErrorId.ERR_DUPLICATE_KEY: 409,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_STALE_UNIT_VERSION: 412,
    ApiErrorId.ERR_UNIT_NOT_RESERVABLE: 409,
    ApiErrorId.ERR_TRADEIN_NOT_OFFERED: 409,
    ApiErrorId.ERR_RECALL_CANNOT_DENY: 409,
    ApiErrorId.ERR_AUCTION_WINDOW: 409,
    ApiErrorId.ERR_BID_TOO_LOW: 409,
    ApiErrorId.ERR_CURTAILMENT_SHORT: 409,
    ApiErrorId.ERR_PARTS_SHORTAGE: 409,
    ApiErrorId.ERR_NO_MATCHING_UNIT: 409,
}

# Register with the framework so validate_error() auto-checks HTTP status.
set_error_http_status_map({k.value: v for k, v in HTTP_STATUS_CODES.items()})
