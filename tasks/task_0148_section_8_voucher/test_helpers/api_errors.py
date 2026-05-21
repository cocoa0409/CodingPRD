"""Error IDs and HTTP status mapping — PRD §5 Error Code Catalogue.

After definition the mapping is registered with the framework so
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
    ERR_AUTH_REQUIRED = "ERR_AUTH_REQUIRED"
    ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
    # Existence
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_FK_NOT_FOUND = "ERR_FK_NOT_FOUND"
    # State / OCC
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    # Voucher gates — PRD §2.10, §3.7
    ERR_VOUCHER_EXPIRED = "ERR_VOUCHER_EXPIRED"
    ERR_VOUCHER_NOT_LOCAL = "ERR_VOUCHER_NOT_LOCAL"
    # Inspector scope — PRD §3.5
    ERR_INSPECTOR_OUT_OF_SCOPE = "ERR_INSPECTOR_OUT_OF_SCOPE"
    # Mobility — PRD §3.7
    ERR_MOBILITY_ZONE_VIOLATION = "ERR_MOBILITY_ZONE_VIOLATION"
    # Inspection outcome — PRD §3.5
    ERR_INSPECTION_OUTCOME_MISMATCH = "ERR_INSPECTION_OUTCOME_MISMATCH"
    # Tenancy constraints — PRD §3.4
    ERR_UNIT_TOO_SMALL = "ERR_UNIT_TOO_SMALL"
    ERR_LEASE_START_AFTER_DEADLINE = "ERR_LEASE_START_AFTER_DEADLINE"
    # Rent reasonableness — PRD §3.6
    ERR_INSUFFICIENT_COMPARABLES = "ERR_INSUFFICIENT_COMPARABLES"
    # Unit occupancy — PRD §3.4
    ERR_UNIT_NOT_VACANT = "ERR_UNIT_NOT_VACANT"
    ERR_UNIT_OCCUPANCY_OVERLAP = "ERR_UNIT_OCCUPANCY_OVERLAP"
    # Inspection timing — PRD §3.5
    ERR_INSPECTION_TOO_SOON = "ERR_INSPECTION_TOO_SOON"
    ERR_INSPECTION_ALREADY_COMPLETED = "ERR_INSPECTION_ALREADY_COMPLETED"
    # Finalize fiscal gates — PRD §3.7
    ERR_RENT_BURDEN_EXCEEDED = "ERR_RENT_BURDEN_EXCEEDED"
    ERR_RENT_BURDEN_DIVZERO = "ERR_RENT_BURDEN_DIVZERO"
    ERR_RENT_NOT_REASONABLE = "ERR_RENT_NOT_REASONABLE"
    # Portability — PRD §3.10
    ERR_INVALID_RECEIVING_PHA = "ERR_INVALID_RECEIVING_PHA"
    # Annual review window — PRD §3.9
    ERR_REVIEW_WINDOW_CLOSED = "ERR_REVIEW_WINDOW_CLOSED"
    # Generic validation — PRD §2.10
    ERR_VALIDATION = "ERR_VALIDATION"


# PRD §5 — Error Code Catalogue.
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_AUTH_REQUIRED: 401,
    ApiErrorId.ERR_FORBIDDEN_ROLE: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_FK_NOT_FOUND: 422,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_VOUCHER_EXPIRED: 409,
    ApiErrorId.ERR_VOUCHER_NOT_LOCAL: 403,
    ApiErrorId.ERR_INSPECTOR_OUT_OF_SCOPE: 403,
    ApiErrorId.ERR_MOBILITY_ZONE_VIOLATION: 422,
    ApiErrorId.ERR_INSPECTION_OUTCOME_MISMATCH: 422,
    ApiErrorId.ERR_UNIT_TOO_SMALL: 422,
    ApiErrorId.ERR_LEASE_START_AFTER_DEADLINE: 422,
    ApiErrorId.ERR_INSUFFICIENT_COMPARABLES: 422,
    ApiErrorId.ERR_UNIT_NOT_VACANT: 409,
    ApiErrorId.ERR_UNIT_OCCUPANCY_OVERLAP: 409,
    ApiErrorId.ERR_INSPECTION_TOO_SOON: 409,
    ApiErrorId.ERR_INSPECTION_ALREADY_COMPLETED: 409,
    ApiErrorId.ERR_RENT_BURDEN_EXCEEDED: 422,
    ApiErrorId.ERR_RENT_BURDEN_DIVZERO: 422,
    ApiErrorId.ERR_RENT_NOT_REASONABLE: 422,
    ApiErrorId.ERR_INVALID_RECEIVING_PHA: 422,
    ApiErrorId.ERR_REVIEW_WINDOW_CLOSED: 409,
    ApiErrorId.ERR_VALIDATION: 422,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
