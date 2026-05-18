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
    # Auth — PRD §2.1
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_OWNERSHIP_MISMATCH = "ERR_OWNERSHIP_MISMATCH"

    # Existence — PRD §2.5
    ERR_NOT_FOUND = "ERR_NOT_FOUND"

    # Generic schema — PRD §5
    ERR_VALIDATION_FAILED = "ERR_VALIDATION_FAILED"

    # State / OCC — PRD §2.9, §2.10
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_VERSION_MISMATCH = "ERR_VERSION_MISMATCH"

    # Assessment lifecycle — PRD §3.2, §3.5
    ERR_DUPLICATE_ROLL_YEAR = "ERR_DUPLICATE_ROLL_YEAR"
    ERR_APPEAL_WINDOW_CLOSED = "ERR_APPEAL_WINDOW_CLOSED"
    ERR_ASSESSMENT_NOT_FINALIZED = "ERR_ASSESSMENT_NOT_FINALIZED"

    # Hearing scheduling — PRD §3.5, §2.8
    ERR_HEARING_INTERVAL_INVALID = "ERR_HEARING_INTERVAL_INVALID"
    ERR_ROOM_DOUBLE_BOOKED = "ERR_ROOM_DOUBLE_BOOKED"
    ERR_OFFICER_BUFFER_VIOLATED = "ERR_OFFICER_BUFFER_VIOLATED"
    ERR_BOE_OFFICER_CONFLICT = "ERR_BOE_OFFICER_CONFLICT"
    ERR_OFFICER_MISMATCH = "ERR_OFFICER_MISMATCH"
    ERR_DECISION_VALUE_INCONSISTENT = "ERR_DECISION_VALUE_INCONSISTENT"

    # Exemptions — PRD §3.3, §3.4
    ERR_EXEMPTION_DUPLICATE = "ERR_EXEMPTION_DUPLICATE"
    ERR_EXEMPTION_INELIGIBLE = "ERR_EXEMPTION_INELIGIBLE"
    ERR_EXEMPTIONS_PENDING = "ERR_EXEMPTIONS_PENDING"

    # Tax bill / payments — PRD §3.4
    ERR_OVERPAYMENT = "ERR_OVERPAYMENT"
    ERR_DUPLICATE_BILL = "ERR_DUPLICATE_BILL"

    # Deferral — PRD §3.6
    ERR_DEFERRAL_NOT_ELIGIBLE = "ERR_DEFERRAL_NOT_ELIGIBLE"


# PRD §5 Error Code Catalogue — HTTP status per error_id.
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_OWNERSHIP_MISMATCH: 403,
    ApiErrorId.ERR_BOE_OFFICER_CONFLICT: 403,
    ApiErrorId.ERR_OFFICER_MISMATCH: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_VALIDATION_FAILED: 400,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_VERSION_MISMATCH: 409,
    ApiErrorId.ERR_DUPLICATE_ROLL_YEAR: 409,
    ApiErrorId.ERR_APPEAL_WINDOW_CLOSED: 409,
    ApiErrorId.ERR_ASSESSMENT_NOT_FINALIZED: 409,
    ApiErrorId.ERR_ROOM_DOUBLE_BOOKED: 409,
    ApiErrorId.ERR_OFFICER_BUFFER_VIOLATED: 409,
    ApiErrorId.ERR_EXEMPTION_DUPLICATE: 409,
    ApiErrorId.ERR_OVERPAYMENT: 409,
    ApiErrorId.ERR_DUPLICATE_BILL: 409,
    ApiErrorId.ERR_EXEMPTIONS_PENDING: 409,
    ApiErrorId.ERR_HEARING_INTERVAL_INVALID: 422,
    ApiErrorId.ERR_DECISION_VALUE_INCONSISTENT: 422,
    ApiErrorId.ERR_EXEMPTION_INELIGIBLE: 422,
    ApiErrorId.ERR_DEFERRAL_NOT_ELIGIBLE: 422,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
