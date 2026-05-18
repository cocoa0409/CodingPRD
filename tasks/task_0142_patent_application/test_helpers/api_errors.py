"""Error IDs and HTTP status mapping (PRD §5 Error Code Catalogue).

After definition the mapping is registered with the framework so that
validate_error() can auto-check HTTP status codes without each test
passing them explicitly.
"""
from __future__ import annotations

from enum import Enum

from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    # Auth / authorization (PRD §2.1)
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"

    # Existence (PRD §2.6)
    ERR_NOT_FOUND = "ERR_NOT_FOUND"

    # State / lifecycle (PRD §2.10 / §2.11)
    ERR_INVALID_STATE = "ERR_INVALID_STATE"

    # Concurrency (PRD §2.5 / §2.11)
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"

    # Idempotency (PRD §2.12)
    ERR_IDEMPOTENCY_CONFLICT = "ERR_IDEMPOTENCY_CONFLICT"

    # Continuation / business referential (PRD §3.2 / §2.11)
    ERR_PARENT_NOT_PENDING = "ERR_PARENT_NOT_PENDING"

    # Claim shape (PRD §3.2)
    ERR_CLAIM_SHAPE_INVALID = "ERR_CLAIM_SHAPE_INVALID"

    # Micro entity (PRD §3.1)
    ERR_MICRO_INELIGIBLE = "ERR_MICRO_INELIGIBLE"

    # Office Action temporal (PRD §3.3)
    ERR_OFFICE_ACTION_DEADLINE_PASSED = "ERR_OFFICE_ACTION_DEADLINE_PASSED"

    # Maintenance temporal (PRD §3.5)
    ERR_MAINTENANCE_WINDOW_CLOSED = "ERR_MAINTENANCE_WINDOW_CLOSED"

    # Maintenance applicability (PRD §3.4 / §3.5)
    ERR_MAINTENANCE_NOT_APPLICABLE = "ERR_MAINTENANCE_NOT_APPLICABLE"

    # PCT (PRD §3.6)
    ERR_PCT_INELIGIBLE = "ERR_PCT_INELIGIBLE"
    ERR_PCT_DEADLINE_PASSED = "ERR_PCT_DEADLINE_PASSED"

    # Fees (PRD §3.2 etc.)
    ERR_FEE_AMOUNT_MISMATCH = "ERR_FEE_AMOUNT_MISMATCH"
    ERR_FEE_CATEGORY_INVALID = "ERR_FEE_CATEGORY_INVALID"

    # Applicant suspension (PRD §3.1)
    ERR_APPLICANT_SUSPENDED = "ERR_APPLICANT_SUSPENDED"

    # Generic validation (PRD §2.11)
    ERR_VALIDATION = "ERR_VALIDATION"


# Per PRD §5 Error Code Catalogue.
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_IDEMPOTENCY_CONFLICT: 409,
    ApiErrorId.ERR_OFFICE_ACTION_DEADLINE_PASSED: 409,
    ApiErrorId.ERR_MAINTENANCE_WINDOW_CLOSED: 409,
    ApiErrorId.ERR_PCT_DEADLINE_PASSED: 409,
    ApiErrorId.ERR_PARENT_NOT_PENDING: 422,
    ApiErrorId.ERR_CLAIM_SHAPE_INVALID: 422,
    ApiErrorId.ERR_MICRO_INELIGIBLE: 422,
    ApiErrorId.ERR_MAINTENANCE_NOT_APPLICABLE: 422,
    ApiErrorId.ERR_PCT_INELIGIBLE: 422,
    ApiErrorId.ERR_FEE_AMOUNT_MISMATCH: 422,
    ApiErrorId.ERR_FEE_CATEGORY_INVALID: 422,
    ApiErrorId.ERR_APPLICANT_SUSPENDED: 403,
    ApiErrorId.ERR_VALIDATION: 422,
}


# Register with the framework so validate_error() auto-checks HTTP status.
set_error_http_status_map({k.value: v for k, v in HTTP_STATUS_CODES.items()})


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
