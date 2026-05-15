"""Error IDs and HTTP status mapping (PRD §5 Error Code Catalogue).

After definition, the mapping is registered with the framework so
validate_error() can auto-check HTTP status codes without each test
passing them explicitly.
"""
from __future__ import annotations

from enum import Enum

from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_PRICING_PROFILE_NOT_FOUND = "ERR_PRICING_PROFILE_NOT_FOUND"
    ERR_BAD_REQUEST = "ERR_BAD_REQUEST"
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_COMPARTMENT_FAULT = "ERR_COMPARTMENT_FAULT"
    ERR_COMPARTMENT_UNAVAILABLE = "ERR_COMPARTMENT_UNAVAILABLE"
    ERR_CABINET_OFFLINE = "ERR_CABINET_OFFLINE"
    ERR_INVALID_INSURANCE = "ERR_INVALID_INSURANCE"
    ERR_RENEWAL_NOT_PERMITTED = "ERR_RENEWAL_NOT_PERMITTED"
    ERR_CLAIM_ALREADY_OPEN = "ERR_CLAIM_ALREADY_OPEN"
    ERR_CLAIM_WINDOW_EXPIRED = "ERR_CLAIM_WINDOW_EXPIRED"
    ERR_REFUND_BLOCKED_BY_CLAIM = "ERR_REFUND_BLOCKED_BY_CLAIM"
    ERR_PAYOUT_EXCEEDS_CAP = "ERR_PAYOUT_EXCEEDS_CAP"
    ERR_DUPLICATE_PROFILE = "ERR_DUPLICATE_PROFILE"
    ERR_DUPLICATE_SLOT = "ERR_DUPLICATE_SLOT"


# Per PRD §5 Error Code Catalogue.
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHORIZED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_PRICING_PROFILE_NOT_FOUND: 404,
    ApiErrorId.ERR_BAD_REQUEST: 422,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_COMPARTMENT_FAULT: 409,
    ApiErrorId.ERR_COMPARTMENT_UNAVAILABLE: 409,
    ApiErrorId.ERR_CABINET_OFFLINE: 409,
    ApiErrorId.ERR_INVALID_INSURANCE: 422,
    ApiErrorId.ERR_RENEWAL_NOT_PERMITTED: 409,
    ApiErrorId.ERR_CLAIM_ALREADY_OPEN: 409,
    ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED: 409,
    ApiErrorId.ERR_REFUND_BLOCKED_BY_CLAIM: 409,
    ApiErrorId.ERR_PAYOUT_EXCEEDS_CAP: 422,
    ApiErrorId.ERR_DUPLICATE_PROFILE: 409,
    ApiErrorId.ERR_DUPLICATE_SLOT: 409,
}


# Register with framework so validate_error() can cross-check HTTP statuses.
set_error_http_status_map({k.value: v for k, v in HTTP_STATUS_CODES.items()})


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
