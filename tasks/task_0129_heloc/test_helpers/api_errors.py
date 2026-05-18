"""Error IDs and HTTP status mapping (PRD §5 Error Code Catalogue).

After definition, the mapping is registered with the framework so
validate_error() can auto-check HTTP status codes without each test
passing them explicitly.
"""
from __future__ import annotations

from enum import Enum

from prd_bench_local_runner.testing.validators import (
    set_error_http_status_map,
)


class ApiErrorId(str, Enum):
    # ---- Auth — PRD §2.1, §2.10 ----
    ERR_MISSING_AUTH = "ERR_MISSING_AUTH"
    ERR_UNKNOWN_ROLE = "ERR_UNKNOWN_ROLE"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"

    # ---- Existence — PRD §2.7 ----
    ERR_RESOURCE_NOT_FOUND = "ERR_RESOURCE_NOT_FOUND"

    # ---- State / concurrency — PRD §2.5, §3 ----
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
    ERR_HELOC_DEFAULTED = "ERR_HELOC_DEFAULTED"
    ERR_HELOC_CLOSED = "ERR_HELOC_CLOSED"
    ERR_DRAW_PERIOD_ENDED = "ERR_DRAW_PERIOD_ENDED"
    ERR_ALREADY_BANKRUPT = "ERR_ALREADY_BANKRUPT"

    # ---- Business safety / fiscal — PRD §3.2, §3.3, §3.4, §3.9 ----
    ERR_BALANCE_NOT_ZERO = "ERR_BALANCE_NOT_ZERO"
    ERR_OCCUPANCY_NOT_PRIMARY = "ERR_OCCUPANCY_NOT_PRIMARY"
    ERR_NO_SENIOR_LIEN = "ERR_NO_SENIOR_LIEN"
    ERR_BORROWER_BANKRUPT = "ERR_BORROWER_BANKRUPT"
    ERR_CLTV_EXCEEDED = "ERR_CLTV_EXCEEDED"
    ERR_BORROWER_PROPERTY_MISMATCH = "ERR_BORROWER_PROPERTY_MISMATCH"
    ERR_PAYMENT_BELOW_MINIMUM = "ERR_PAYMENT_BELOW_MINIMUM"
    ERR_RATE_BOUND_INVALID = "ERR_RATE_BOUND_INVALID"
    ERR_INSUFFICIENT_AVAILABLE_CREDIT = "ERR_INSUFFICIENT_AVAILABLE_CREDIT"

    # ---- Field-shape validation — PRD §2.12 ----
    ERR_VALIDATION_FAILED = "ERR_VALIDATION_FAILED"


# PRD §5 Error Code Catalogue — http status per error_id.
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_MISSING_AUTH: 401,
    ApiErrorId.ERR_UNKNOWN_ROLE: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_SEGREGATION_OF_DUTIES: 403,
    ApiErrorId.ERR_RESOURCE_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_HELOC_DEFAULTED: 409,
    ApiErrorId.ERR_HELOC_CLOSED: 409,
    ApiErrorId.ERR_DRAW_PERIOD_ENDED: 409,
    ApiErrorId.ERR_ALREADY_BANKRUPT: 409,
    ApiErrorId.ERR_BALANCE_NOT_ZERO: 422,
    ApiErrorId.ERR_OCCUPANCY_NOT_PRIMARY: 422,
    ApiErrorId.ERR_NO_SENIOR_LIEN: 422,
    ApiErrorId.ERR_BORROWER_BANKRUPT: 422,
    ApiErrorId.ERR_CLTV_EXCEEDED: 422,
    ApiErrorId.ERR_BORROWER_PROPERTY_MISMATCH: 422,
    ApiErrorId.ERR_PAYMENT_BELOW_MINIMUM: 422,
    ApiErrorId.ERR_RATE_BOUND_INVALID: 422,
    ApiErrorId.ERR_INSUFFICIENT_AVAILABLE_CREDIT: 422,
    ApiErrorId.ERR_VALIDATION_FAILED: 400,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
