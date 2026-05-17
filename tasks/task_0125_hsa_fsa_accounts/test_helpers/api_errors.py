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
    # Schema / primitive — PRD §5
    ERR_BAD_REQUEST = "ERR_BAD_REQUEST"

    # Auth — PRD §2.1
    ERR_MISSING_AUTH = "ERR_MISSING_AUTH"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"

    # Existence — PRD §2.6
    ERR_NOT_FOUND = "ERR_NOT_FOUND"

    # State — PRD §2.10
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_ACCOUNT_NOT_OPEN = "ERR_ACCOUNT_NOT_OPEN"
    ERR_ACCOUNT_HAS_OPEN_PLAN_YEAR = "ERR_ACCOUNT_HAS_OPEN_PLAN_YEAR"
    ERR_ACCOUNT_HAS_PENDING_CLAIMS = "ERR_ACCOUNT_HAS_PENDING_CLAIMS"
    ERR_PLAN_YEAR_NOT_CLAIMABLE = "ERR_PLAN_YEAR_NOT_CLAIMABLE"

    # Business constraints — PRD §3.2, §3.7
    ERR_DUPLICATE_PLAN_YEAR = "ERR_DUPLICATE_PLAN_YEAR"
    ERR_DUPLICATE_OPS_RUN = "ERR_DUPLICATE_OPS_RUN"
    ERR_OPS_RUN_NOT_MONOTONIC = "ERR_OPS_RUN_NOT_MONOTONIC"

    # Fiscal — PRD §3.3, §3.5
    ERR_INSUFFICIENT_BALANCE = "ERR_INSUFFICIENT_BALANCE"
    ERR_REVERSAL_WOULD_OVERDRAW = "ERR_REVERSAL_WOULD_OVERDRAW"
    ERR_CONTRIBUTION_CAP_EXCEEDED = "ERR_CONTRIBUTION_CAP_EXCEEDED"

    # Referential — PRD §3.5
    ERR_DEPENDENT_INACTIVE = "ERR_DEPENDENT_INACTIVE"
    ERR_DEPENDENT_REQUIRED = "ERR_DEPENDENT_REQUIRED"
    ERR_EXPENSE_NOT_ELIGIBLE = "ERR_EXPENSE_NOT_ELIGIBLE"
    ERR_NO_ELIGIBLE_PLAN_YEAR = "ERR_NO_ELIGIBLE_PLAN_YEAR"

    # Adjudication body — PRD §3.5
    ERR_DENIAL_REASON_REQUIRED = "ERR_DENIAL_REASON_REQUIRED"

    # Audit reconciliation — PRD §2.8, §3.9
    ERR_AUDIT_TRAIL_INCONSISTENT = "ERR_AUDIT_TRAIL_INCONSISTENT"


# PRD §5 Error Code Catalogue — http status per error_id.
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_BAD_REQUEST: 400,
    ApiErrorId.ERR_MISSING_AUTH: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_SEGREGATION_OF_DUTIES: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_ACCOUNT_NOT_OPEN: 409,
    ApiErrorId.ERR_ACCOUNT_HAS_OPEN_PLAN_YEAR: 409,
    ApiErrorId.ERR_ACCOUNT_HAS_PENDING_CLAIMS: 409,
    ApiErrorId.ERR_PLAN_YEAR_NOT_CLAIMABLE: 409,
    ApiErrorId.ERR_DUPLICATE_PLAN_YEAR: 409,
    ApiErrorId.ERR_DUPLICATE_OPS_RUN: 409,
    ApiErrorId.ERR_OPS_RUN_NOT_MONOTONIC: 409,
    ApiErrorId.ERR_INSUFFICIENT_BALANCE: 409,
    ApiErrorId.ERR_REVERSAL_WOULD_OVERDRAW: 409,
    ApiErrorId.ERR_DEPENDENT_INACTIVE: 409,
    ApiErrorId.ERR_AUDIT_TRAIL_INCONSISTENT: 409,
    ApiErrorId.ERR_DENIAL_REASON_REQUIRED: 422,
    ApiErrorId.ERR_CONTRIBUTION_CAP_EXCEEDED: 422,
    ApiErrorId.ERR_EXPENSE_NOT_ELIGIBLE: 422,
    ApiErrorId.ERR_DEPENDENT_REQUIRED: 422,
    ApiErrorId.ERR_NO_ELIGIBLE_PLAN_YEAR: 422,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
