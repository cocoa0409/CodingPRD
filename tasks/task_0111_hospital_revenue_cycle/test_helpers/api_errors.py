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
    ERR_AUTH_MISSING = "ERR_AUTH_MISSING"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"

    # Existence — PRD §2.4
    ERR_NOT_FOUND = "ERR_NOT_FOUND"

    # State / concurrency — PRD §2.6 + §5
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"

    # Business — PRD §3.2 / §3.3 / §3.6 / §3.7 / §3.8
    ERR_POLICY_PATIENT_MISMATCH = "ERR_POLICY_PATIENT_MISMATCH"
    ERR_PLAN_YEAR_EXPIRED = "ERR_PLAN_YEAR_EXPIRED"
    ERR_INVALID_ICD10 = "ERR_INVALID_ICD10"
    ERR_INVALID_CPT = "ERR_INVALID_CPT"
    ERR_CODING_CPT_MISMATCH = "ERR_CODING_CPT_MISMATCH"
    ERR_ALLOWED_EXCEEDS_CHARGES = "ERR_ALLOWED_EXCEEDS_CHARGES"
    ERR_INVALID_CLEARANCE_PAYLOAD = "ERR_INVALID_CLEARANCE_PAYLOAD"
    ERR_CHARGES_NOT_READY = "ERR_CHARGES_NOT_READY"
    ERR_WRITE_OFF_TOO_EARLY = "ERR_WRITE_OFF_TOO_EARLY"
    ERR_WRITE_OFF_NO_BALANCE = "ERR_WRITE_OFF_NO_BALANCE"
    ERR_PAYMENT_AMOUNT_INVALID = "ERR_PAYMENT_AMOUNT_INVALID"

    # Concurrency / duplicate — PRD §3.6 / §3.8
    ERR_DUPLICATE_CODING_RECORD = "ERR_DUPLICATE_CODING_RECORD"
    ERR_DUPLICATE_WRITE_OFF = "ERR_DUPLICATE_WRITE_OFF"


HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_AUTH_MISSING: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_POLICY_PATIENT_MISMATCH: 422,
    ApiErrorId.ERR_PLAN_YEAR_EXPIRED: 422,
    ApiErrorId.ERR_INVALID_ICD10: 422,
    ApiErrorId.ERR_INVALID_CPT: 422,
    ApiErrorId.ERR_CODING_CPT_MISMATCH: 422,
    ApiErrorId.ERR_ALLOWED_EXCEEDS_CHARGES: 422,
    ApiErrorId.ERR_INVALID_CLEARANCE_PAYLOAD: 422,
    ApiErrorId.ERR_CHARGES_NOT_READY: 422,
    ApiErrorId.ERR_WRITE_OFF_TOO_EARLY: 422,
    ApiErrorId.ERR_WRITE_OFF_NO_BALANCE: 422,
    ApiErrorId.ERR_PAYMENT_AMOUNT_INVALID: 422,
    ApiErrorId.ERR_DUPLICATE_CODING_RECORD: 409,
    ApiErrorId.ERR_DUPLICATE_WRITE_OFF: 409,
}


# Register with the framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
