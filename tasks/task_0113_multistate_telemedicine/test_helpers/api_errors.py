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
    # Auth / RBAC — PRD §2.1
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"

    # Existence — PRD §2.6
    ERR_NOT_FOUND = "ERR_NOT_FOUND"

    # State / concurrency — PRD §2.5, §2.6
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"

    # Business referential — PRD §3.4
    ERR_PHYSICIAN_MISMATCH = "ERR_PHYSICIAN_MISMATCH"

    # Business safety — PRD §3.3, §3.4
    ERR_NO_VALID_LICENSE = "ERR_NO_VALID_LICENSE"
    ERR_DEA_REQUIREMENTS_NOT_MET = "ERR_DEA_REQUIREMENTS_NOT_MET"
    ERR_SCHEDULE_II_REFILLS_FORBIDDEN = "ERR_SCHEDULE_II_REFILLS_FORBIDDEN"
    ERR_COMPLIANCE_SCORE_TOO_LOW = "ERR_COMPLIANCE_SCORE_TOO_LOW"

    # Business constraint — PRD §3.3, §3.4, §3.7
    ERR_INSURANCE_NOT_ENROLLED = "ERR_INSURANCE_NOT_ENROLLED"
    ERR_RX_FIELD_OUT_OF_RANGE = "ERR_RX_FIELD_OUT_OF_RANGE"
    ERR_FOLLOWUP_WINDOW_EMPTY = "ERR_FOLLOWUP_WINDOW_EMPTY"
    ERR_BILLING_NOT_TERMINAL = "ERR_BILLING_NOT_TERMINAL"
    ERR_CLAIM_ALREADY_EXISTS = "ERR_CLAIM_ALREADY_EXISTS"
    ERR_PATIENT_HAS_ACTIVE_CONSULT = "ERR_PATIENT_HAS_ACTIVE_CONSULT"
    ERR_LICENSE_PERIOD_OVERLAP = "ERR_LICENSE_PERIOD_OVERLAP"

    # Pagination — PRD §2.3
    ERR_PAGINATION_INVALID = "ERR_PAGINATION_INVALID"


# PRD §5 Error Code Catalogue — http status per error_id.
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_NO_VALID_LICENSE: 422,
    ApiErrorId.ERR_DEA_REQUIREMENTS_NOT_MET: 422,
    ApiErrorId.ERR_SCHEDULE_II_REFILLS_FORBIDDEN: 422,
    ApiErrorId.ERR_COMPLIANCE_SCORE_TOO_LOW: 422,
    ApiErrorId.ERR_PHYSICIAN_MISMATCH: 422,
    ApiErrorId.ERR_INSURANCE_NOT_ENROLLED: 422,
    ApiErrorId.ERR_RX_FIELD_OUT_OF_RANGE: 422,
    ApiErrorId.ERR_FOLLOWUP_WINDOW_EMPTY: 422,
    ApiErrorId.ERR_BILLING_NOT_TERMINAL: 409,
    ApiErrorId.ERR_CLAIM_ALREADY_EXISTS: 409,
    ApiErrorId.ERR_PATIENT_HAS_ACTIVE_CONSULT: 409,
    ApiErrorId.ERR_LICENSE_PERIOD_OVERLAP: 409,
    ApiErrorId.ERR_PAGINATION_INVALID: 400,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
