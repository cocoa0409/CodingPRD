"""Error IDs and HTTP status mapping (PRD §5 Error Code Catalogue).

The mapping is registered with the framework so validate_error() can auto-check
the HTTP status that accompanies each error_id.
"""
from enum import Enum
from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    # Auth / existence / request
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
    # State / posture / OCC
    ERR_VENUE_NOT_OPEN = "ERR_VENUE_NOT_OPEN"
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_STALE_SLOT_VERSION = "ERR_STALE_SLOT_VERSION"
    ERR_STALE_GROUP_VERSION = "ERR_STALE_GROUP_VERSION"
    # Safety
    ERR_HEIGHT_REQUIREMENT = "ERR_HEIGHT_REQUIREMENT"
    ERR_WAIVER_REQUIRED = "ERR_WAIVER_REQUIRED"
    # Temporal / capacity / constraint
    ERR_ATTRACTION_KIND_MISMATCH = "ERR_ATTRACTION_KIND_MISMATCH"
    ERR_CHECK_IN_WINDOW = "ERR_CHECK_IN_WINDOW"
    ERR_NO_SHOW_WINDOW = "ERR_NO_SHOW_WINDOW"
    ERR_PARTY_GROUP_EMPTY = "ERR_PARTY_GROUP_EMPTY"
    ERR_SLOT_OVERLAP = "ERR_SLOT_OVERLAP"
    ERR_CAPACITY_EXCEEDED = "ERR_CAPACITY_EXCEEDED"
    ERR_WRISTBAND_CAP_EXCEEDED = "ERR_WRISTBAND_CAP_EXCEEDED"
    # Fiscal / referential
    ERR_COMBO_PASS_INVALID = "ERR_COMBO_PASS_INVALID"
    ERR_INSUFFICIENT_CARD_BALANCE = "ERR_INSUFFICIENT_CARD_BALANCE"


HTTP_STATUS_CODES: dict[str, int] = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_REQUEST: 422,
    ApiErrorId.ERR_VENUE_NOT_OPEN: 409,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_STALE_SLOT_VERSION: 412,
    ApiErrorId.ERR_STALE_GROUP_VERSION: 412,
    ApiErrorId.ERR_HEIGHT_REQUIREMENT: 422,
    ApiErrorId.ERR_WAIVER_REQUIRED: 422,
    ApiErrorId.ERR_ATTRACTION_KIND_MISMATCH: 409,
    ApiErrorId.ERR_CHECK_IN_WINDOW: 409,
    ApiErrorId.ERR_NO_SHOW_WINDOW: 409,
    ApiErrorId.ERR_PARTY_GROUP_EMPTY: 409,
    ApiErrorId.ERR_SLOT_OVERLAP: 409,
    ApiErrorId.ERR_CAPACITY_EXCEEDED: 409,
    ApiErrorId.ERR_WRISTBAND_CAP_EXCEEDED: 422,
    ApiErrorId.ERR_COMBO_PASS_INVALID: 409,
    ApiErrorId.ERR_INSUFFICIENT_CARD_BALANCE: 409,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(HTTP_STATUS_CODES)
