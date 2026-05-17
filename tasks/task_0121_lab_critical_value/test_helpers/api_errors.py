"""Error IDs and HTTP status mapping (PRD §5 Error Code Catalogue).

After definition, the mapping is registered with the framework so
validate_error() can auto-check HTTP status codes without each test
having to pass the expected status explicitly.
"""
from __future__ import annotations

from enum import Enum

from prd_bench_local_runner.testing.validators import (
    set_error_http_status_map,
)


class ApiErrorId(str, Enum):
    # Auth / RBAC — PRD §2.1.
    ERR_AUTH_REQUIRED = "ERR_AUTH_REQUIRED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"

    # Existence — PRD §2.5.
    ERR_NOT_FOUND = "ERR_NOT_FOUND"

    # State eligibility — PRD §3 state machines.
    ERR_INVALID_STATE = "ERR_INVALID_STATE"

    # Optimistic concurrency — PRD §2.10.
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"

    # CLIA business-safety — PRD §2.6.
    ERR_CLIA_SOD_VIOLATION = "ERR_CLIA_SOD_VIOLATION"
    ERR_CLIA_COMPLEXITY_VIOLATION = "ERR_CLIA_COMPLEXITY_VIOLATION"

    # Patient consent — PRD §2.7.
    ERR_PATIENT_CONSENT_BLOCKED = "ERR_PATIENT_CONSENT_BLOCKED"

    # Acknowledgement integrity — PRD §3.5.
    ERR_ACK_BY_WRONG_RECIPIENT = "ERR_ACK_BY_WRONG_RECIPIENT"
    ERR_READBACK_INCOMPLETE = "ERR_READBACK_INCOMPLETE"

    # Time / transport invariants — PRD §2.8.
    ERR_TIME_ORDER_INVALID = "ERR_TIME_ORDER_INVALID"
    ERR_TRANSPORT_CHAIN_BROKEN = "ERR_TRANSPORT_CHAIN_BROKEN"

    # Resulting completeness — PRD §3.4.
    ERR_MEASUREMENTS_INCOMPLETE = "ERR_MEASUREMENTS_INCOMPLETE"

    # Active-clinician constraint — PRD §2.6.
    ERR_CLINICIAN_INACTIVE = "ERR_CLINICIAN_INACTIVE"

    # Acknowledgement double-fire — PRD §3.5 / §2.12.
    ERR_ALREADY_ACKNOWLEDGED = "ERR_ALREADY_ACKNOWLEDGED"

    # Transport-leg arrival race — PRD §2.12.
    ERR_LEG_ALREADY_ARRIVED = "ERR_LEG_ALREADY_ARRIVED"

    # Specimen uniqueness race — PRD §2.12.
    ERR_SPECIMEN_ALREADY_EXISTS = "ERR_SPECIMEN_ALREADY_EXISTS"

    # Pagination — PRD §2.3.
    ERR_INVALID_PAGINATION = "ERR_INVALID_PAGINATION"

    # Generic input validation — PRD §2.13.
    ERR_VALIDATION = "ERR_VALIDATION"


# PRD §5 Error Code Catalogue — explicit HTTP status mapping.
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_AUTH_REQUIRED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_CLIA_SOD_VIOLATION: 422,
    ApiErrorId.ERR_CLIA_COMPLEXITY_VIOLATION: 422,
    ApiErrorId.ERR_PATIENT_CONSENT_BLOCKED: 422,
    ApiErrorId.ERR_ACK_BY_WRONG_RECIPIENT: 422,
    ApiErrorId.ERR_READBACK_INCOMPLETE: 422,
    ApiErrorId.ERR_TIME_ORDER_INVALID: 422,
    ApiErrorId.ERR_TRANSPORT_CHAIN_BROKEN: 422,
    ApiErrorId.ERR_MEASUREMENTS_INCOMPLETE: 422,
    ApiErrorId.ERR_CLINICIAN_INACTIVE: 422,
    ApiErrorId.ERR_ALREADY_ACKNOWLEDGED: 409,
    ApiErrorId.ERR_LEG_ALREADY_ARRIVED: 409,
    ApiErrorId.ERR_SPECIMEN_ALREADY_EXISTS: 409,
    ApiErrorId.ERR_INVALID_PAGINATION: 400,
    ApiErrorId.ERR_VALIDATION: 422,
}


# Register with the framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
