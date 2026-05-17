"""Error IDs and HTTP status mapping (PRD §5 Error Code Catalogue).

After definition the mapping is registered with the framework so
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

    # Existence — PRD §2.5
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"

    # Schema / amount / time validation — PRD §2.6 / §2.7 / §3.6
    ERR_VALIDATION = "ERR_VALIDATION"
    ERR_INVALID_AMOUNT = "ERR_INVALID_AMOUNT"
    ERR_INVALID_TIMERANGE = "ERR_INVALID_TIMERANGE"

    # State eligibility — PRD §2.7 / §3.6 / §3.7 / §3.8
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_SESSION_NOT_OPEN = "ERR_SESSION_NOT_OPEN"
    ERR_APPT_NOT_OPEN = "ERR_APPT_NOT_OPEN"
    ERR_CLAIM_NOT_POSTED = "ERR_CLAIM_NOT_POSTED"

    # Claim void window — PRD §3.8
    ERR_VOID_WINDOW_EXPIRED = "ERR_VOID_WINDOW_EXPIRED"

    # Clinical safety — PRD §3.6 / §3.9
    ERR_SAFETY_PLAN_REQUIRED = "ERR_SAFETY_PLAN_REQUIRED"
    ERR_HIGH_ASSESSMENT_REQUIRED = "ERR_HIGH_ASSESSMENT_REQUIRED"
    ERR_RISK_STILL_HIGH = "ERR_RISK_STILL_HIGH"

    # Therapist credential / licensure — PRD §3.2 / §3.6 / §3.7
    ERR_THERAPIST_NOT_ACTIVE = "ERR_THERAPIST_NOT_ACTIVE"
    ERR_LICENSE_GAP_FOR_STATE = "ERR_LICENSE_GAP_FOR_STATE"
    ERR_NO_ACTIVE_LICENSE = "ERR_NO_ACTIVE_LICENSE"
    ERR_NO_ACTIVE_SUPERVISOR = "ERR_NO_ACTIVE_SUPERVISOR"
    ERR_SUPERVISION_INCOMPLETE = "ERR_SUPERVISION_INCOMPLETE"

    # Scheduling collisions / check-in window — PRD §3.6
    ERR_THERAPIST_DOUBLE_BOOKED = "ERR_THERAPIST_DOUBLE_BOOKED"
    ERR_PATIENT_DOUBLE_BOOKED = "ERR_PATIENT_DOUBLE_BOOKED"
    ERR_OUTSIDE_CHECKIN_WINDOW = "ERR_OUTSIDE_CHECKIN_WINDOW"

    # OCC — PRD §2.4
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"


# PRD §5 Error Code Catalogue — explicit HTTP status mapping.
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_AUTH_REQUIRED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_REFERENCE_NOT_FOUND: 404,
    ApiErrorId.ERR_VALIDATION: 400,
    ApiErrorId.ERR_INVALID_AMOUNT: 422,
    ApiErrorId.ERR_INVALID_TIMERANGE: 422,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_SESSION_NOT_OPEN: 409,
    ApiErrorId.ERR_APPT_NOT_OPEN: 409,
    ApiErrorId.ERR_CLAIM_NOT_POSTED: 409,
    ApiErrorId.ERR_VOID_WINDOW_EXPIRED: 409,
    ApiErrorId.ERR_SAFETY_PLAN_REQUIRED: 409,
    ApiErrorId.ERR_HIGH_ASSESSMENT_REQUIRED: 422,
    ApiErrorId.ERR_RISK_STILL_HIGH: 409,
    ApiErrorId.ERR_THERAPIST_NOT_ACTIVE: 409,
    ApiErrorId.ERR_LICENSE_GAP_FOR_STATE: 409,
    ApiErrorId.ERR_NO_ACTIVE_LICENSE: 409,
    ApiErrorId.ERR_NO_ACTIVE_SUPERVISOR: 409,
    ApiErrorId.ERR_SUPERVISION_INCOMPLETE: 409,
    ApiErrorId.ERR_THERAPIST_DOUBLE_BOOKED: 409,
    ApiErrorId.ERR_PATIENT_DOUBLE_BOOKED: 409,
    ApiErrorId.ERR_OUTSIDE_CHECKIN_WINDOW: 409,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
}


# Register with the framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
