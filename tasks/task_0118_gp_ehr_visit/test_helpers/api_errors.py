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
    ERR_AUTH_REQUIRED = "ERR_AUTH_REQUIRED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"

    # Existence — PRD §2.6 / §2.7
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"

    # State eligibility — PRD §2.7 / §3.3 / §3.4 / §3.5
    ERR_INVALID_ENCOUNTER_STATE = "ERR_INVALID_ENCOUNTER_STATE"
    ERR_INVALID_PRESCRIPTION_STATE = "ERR_INVALID_PRESCRIPTION_STATE"
    ERR_REFERRAL_NOT_PENDING = "ERR_REFERRAL_NOT_PENDING"

    # OCC — PRD §2.5
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"

    # EPCS / controlled-substance — PRD §3.4
    ERR_EPCS_NOT_ENROLLED = "ERR_EPCS_NOT_ENROLLED"
    ERR_SCHEDULE_II_NO_REFILLS = "ERR_SCHEDULE_II_NO_REFILLS"

    # PCP / panel — PRD §3.1
    ERR_PROVIDER_NOT_PCP = "ERR_PROVIDER_NOT_PCP"
    ERR_PCP_ALREADY_BOUND = "ERR_PCP_ALREADY_BOUND"
    ERR_PANEL_FULL = "ERR_PANEL_FULL"

    # Referral integrity — PRD §3.5
    ERR_REFERRER_NOT_PCP = "ERR_REFERRER_NOT_PCP"
    ERR_INVALID_SPECIALIST = "ERR_INVALID_SPECIALIST"

    # Encounter scheduling — PRD §3.3
    ERR_INVALID_TIME_RANGE = "ERR_INVALID_TIME_RANGE"
    ERR_PROVIDER_TIME_CONFLICT = "ERR_PROVIDER_TIME_CONFLICT"
    ERR_PATIENT_TIME_CONFLICT = "ERR_PATIENT_TIME_CONFLICT"

    # Completion / billing — PRD §3.3
    ERR_NO_BILLABLE_LINES = "ERR_NO_BILLABLE_LINES"
    ERR_INVALID_BILLING_UNITS = "ERR_INVALID_BILLING_UNITS"

    # Portal / SoD — PRD §2.12
    ERR_PORTAL_DISABLED = "ERR_PORTAL_DISABLED"
    ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"


# PRD §5 Error Code Catalogue — explicit HTTP status mapping.
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_AUTH_REQUIRED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_REFERENCE_NOT_FOUND: 422,
    ApiErrorId.ERR_INVALID_ENCOUNTER_STATE: 409,
    ApiErrorId.ERR_INVALID_PRESCRIPTION_STATE: 409,
    ApiErrorId.ERR_REFERRAL_NOT_PENDING: 409,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_EPCS_NOT_ENROLLED: 403,
    ApiErrorId.ERR_SCHEDULE_II_NO_REFILLS: 422,
    ApiErrorId.ERR_PROVIDER_NOT_PCP: 422,
    ApiErrorId.ERR_PCP_ALREADY_BOUND: 409,
    ApiErrorId.ERR_PANEL_FULL: 422,
    ApiErrorId.ERR_REFERRER_NOT_PCP: 422,
    ApiErrorId.ERR_INVALID_SPECIALIST: 422,
    ApiErrorId.ERR_INVALID_TIME_RANGE: 422,
    ApiErrorId.ERR_PROVIDER_TIME_CONFLICT: 409,
    ApiErrorId.ERR_PATIENT_TIME_CONFLICT: 409,
    ApiErrorId.ERR_NO_BILLABLE_LINES: 422,
    ApiErrorId.ERR_INVALID_BILLING_UNITS: 422,
    ApiErrorId.ERR_PORTAL_DISABLED: 403,
    ApiErrorId.ERR_SEGREGATION_OF_DUTIES: 403,
}


# Register with the framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
