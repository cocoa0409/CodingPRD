"""Error IDs and HTTP status mapping — PRD §5 Error Code Catalogue.

After definition, the mapping is registered with the framework so
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
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    # Existence — PRD §2.5
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_LIABILITY_NOT_OWNED = "ERR_LIABILITY_NOT_OWNED"
    # State preconditions — PRD §2.10
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_LIABILITY_NOT_ELIGIBLE = "ERR_LIABILITY_NOT_ELIGIBLE"
    # Business safety — PRD §2.8
    ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
    # Business temporal — PRD §3.3
    ERR_CSED_EXPIRED = "ERR_CSED_EXPIRED"
    ERR_OVERLAPPING_TOLLING = "ERR_OVERLAPPING_TOLLING"
    # Cross-workflow lock — PRD §3.4
    ERR_LIABILITY_LOCKED = "ERR_LIABILITY_LOCKED"
    # Business constraints — PRD §3.4 / §3.7 / §3.8
    ERR_DDIA_REQUIRED = "ERR_DDIA_REQUIRED"
    ERR_INELIGIBLE_AGREEMENT_TYPE = "ERR_INELIGIBLE_AGREEMENT_TYPE"
    ERR_DEPOSIT_INSUFFICIENT = "ERR_DEPOSIT_INSUFFICIENT"
    ERR_OIC_BELOW_RCP = "ERR_OIC_BELOW_RCP"
    ERR_LIEN_WITHDRAWAL_NOT_ELIGIBLE = "ERR_LIEN_WITHDRAWAL_NOT_ELIGIBLE"
    # Business fiscal — PRD §3.5
    ERR_OVERPAYMENT = "ERR_OVERPAYMENT"
    # CNC eligibility — PRD §3.11
    ERR_CNC_NOT_ELIGIBLE = "ERR_CNC_NOT_ELIGIBLE"
    # OCC — PRD §2.4
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
    # Body schema — PRD §2.10
    ERR_VALIDATION = "ERR_VALIDATION"


# PRD §5 — Error Code Catalogue (HTTP status mapping).
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_AUTH_REQUIRED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_LIABILITY_NOT_OWNED: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_LIABILITY_NOT_ELIGIBLE: 409,
    ApiErrorId.ERR_CNC_NOT_ELIGIBLE: 422,
    ApiErrorId.ERR_LIABILITY_LOCKED: 409,
    ApiErrorId.ERR_OVERLAPPING_TOLLING: 409,
    ApiErrorId.ERR_DDIA_REQUIRED: 422,
    ApiErrorId.ERR_INELIGIBLE_AGREEMENT_TYPE: 422,
    ApiErrorId.ERR_DEPOSIT_INSUFFICIENT: 422,
    ApiErrorId.ERR_OIC_BELOW_RCP: 422,
    ApiErrorId.ERR_LIEN_WITHDRAWAL_NOT_ELIGIBLE: 422,
    ApiErrorId.ERR_OVERPAYMENT: 422,
    ApiErrorId.ERR_CSED_EXPIRED: 422,
    ApiErrorId.ERR_SEGREGATION_OF_DUTIES: 422,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_VALIDATION: 400,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
