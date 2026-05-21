"""Error IDs and HTTP status mapping — PRD §5.

The mapping is registered with the framework at import time so
validate_error() auto-checks HTTP status codes without each test
passing them explicitly.
"""
from __future__ import annotations

from enum import Enum

from prd_bench_local_runner.testing.validators import (
    set_error_http_status_map,
)


class ApiErrorId(str, Enum):
    # Auth — PRD §2.1
    ERR_AUTH_MISSING = "ERR_AUTH_MISSING"
    ERR_AUTH_INVALID_ROLE = "ERR_AUTH_INVALID_ROLE"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    # Existence — PRD §2.7
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"
    # State checks — PRD §2.11 / §3
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_CARD_NOT_ACTIVE = "ERR_CARD_NOT_ACTIVE"
    ERR_TRIP_ALREADY_OPEN = "ERR_TRIP_ALREADY_OPEN"
    ERR_DUPLICATE_TAP = "ERR_DUPLICATE_TAP"
    # Temporal — PRD §3.5, §3.6
    ERR_CARD_OUTSIDE_VALIDITY = "ERR_CARD_OUTSIDE_VALIDITY"
    ERR_TAP_OUT_NOT_AFTER_TAP_IN = "ERR_TAP_OUT_NOT_AFTER_TAP_IN"
    # Business referential — PRD §3.2
    ERR_MISSING_REDUCED_FARE_CERTIFICATE = "ERR_MISSING_REDUCED_FARE_CERTIFICATE"
    ERR_MISSING_LOW_INCOME_VERIFICATION = "ERR_MISSING_LOW_INCOME_VERIFICATION"
    ERR_CERTIFICATE_WINDOW_OVERLAP = "ERR_CERTIFICATE_WINDOW_OVERLAP"
    # Business constraint — PRD §3.4, §3.5, §3.9
    ERR_DEVICE_ALREADY_BOUND = "ERR_DEVICE_ALREADY_BOUND"
    ERR_INVALID_AMOUNT = "ERR_INVALID_AMOUNT"
    # Business fiscal — PRD §3.9, §3.5
    ERR_FSA_MONTHLY_CAP_EXCEEDED = "ERR_FSA_MONTHLY_CAP_EXCEEDED"
    ERR_INSUFFICIENT_FUNDS = "ERR_INSUFFICIENT_FUNDS"
    # OCC — PRD §2.5
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
    # Pagination — PRD §2.3
    ERR_INVALID_PAGINATION = "ERR_INVALID_PAGINATION"


# PRD §5 — Error Code Catalogue
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_AUTH_MISSING: 401,
    ApiErrorId.ERR_AUTH_INVALID_ROLE: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_REFERENCE_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_CARD_NOT_ACTIVE: 409,
    ApiErrorId.ERR_TRIP_ALREADY_OPEN: 409,
    ApiErrorId.ERR_DUPLICATE_TAP: 409,
    ApiErrorId.ERR_CARD_OUTSIDE_VALIDITY: 422,
    ApiErrorId.ERR_TAP_OUT_NOT_AFTER_TAP_IN: 422,
    ApiErrorId.ERR_MISSING_REDUCED_FARE_CERTIFICATE: 409,
    ApiErrorId.ERR_MISSING_LOW_INCOME_VERIFICATION: 409,
    ApiErrorId.ERR_CERTIFICATE_WINDOW_OVERLAP: 409,
    ApiErrorId.ERR_DEVICE_ALREADY_BOUND: 409,
    ApiErrorId.ERR_INVALID_AMOUNT: 422,
    ApiErrorId.ERR_FSA_MONTHLY_CAP_EXCEEDED: 409,
    ApiErrorId.ERR_INSUFFICIENT_FUNDS: 402,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_INVALID_PAGINATION: 422,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
