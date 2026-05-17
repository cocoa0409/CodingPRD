"""Error IDs and HTTP status mapping (PRD §5 Error Code Catalogue).

After definition the mapping is registered with the framework so
``validate_error()`` auto-checks HTTP status codes without each test
having to pass them explicitly.
"""
from __future__ import annotations

from enum import Enum

from prd_bench_local_runner.testing.validators import (
    set_error_http_status_map,
)


class ApiErrorId(str, Enum):
    # Auth / RBAC — PRD §2.1 / §2.8 rungs 1-2.
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"

    # Existence — PRD §2.7 / §2.8 rung 3.
    ERR_RESOURCE_NOT_FOUND = "ERR_RESOURCE_NOT_FOUND"

    # State / concurrency — PRD §2.6 / §2.8 rung 4.
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"

    # Cross-entity member state — PRD §2.8 rung 5.
    ERR_MEMBER_NOT_ACTIVE = "ERR_MEMBER_NOT_ACTIVE"

    # Business-safety / PA family — PRD §2.8 rung 6-7.
    ERR_SPECIALTY_CHANNEL_REQUIRED = "ERR_SPECIALTY_CHANNEL_REQUIRED"
    ERR_PA_REQUIRED = "ERR_PA_REQUIRED"
    ERR_PA_DENIED = "ERR_PA_DENIED"
    ERR_PA_REVOKED = "ERR_PA_REVOKED"
    ERR_PA_EXPIRED = "ERR_PA_EXPIRED"
    ERR_PA_MISMATCH = "ERR_PA_MISMATCH"
    ERR_PA_REVISION_LIMIT = "ERR_PA_REVISION_LIMIT"

    # Step therapy — PRD §2.8 rung 8.
    ERR_STEP_THERAPY_NOT_SATISFIED = "ERR_STEP_THERAPY_NOT_SATISFIED"

    # Refill-too-soon — PRD §2.8 rung 9.
    ERR_REFILL_TOO_SOON = "ERR_REFILL_TOO_SOON"

    # Channel / days-supply — PRD §2.8 rung 10.
    ERR_CHANNEL_DAYS_SUPPLY_MISMATCH = "ERR_CHANNEL_DAYS_SUPPLY_MISMATCH"

    # Formulary / copay card — PRD §2.8 rung 11-12.
    ERR_DRUG_NOT_ON_FORMULARY = "ERR_DRUG_NOT_ON_FORMULARY"
    ERR_COPAY_CARD_MISMATCH = "ERR_COPAY_CARD_MISMATCH"
    ERR_COPAY_CARD_EXHAUSTED = "ERR_COPAY_CARD_EXHAUSTED"

    # Clawback window — PRD §2.8 rung 14.
    ERR_CLAWBACK_WINDOW_EXPIRED = "ERR_CLAWBACK_WINDOW_EXPIRED"

    # Plan fiscal sanity — PRD §2.8 rung 15.
    ERR_OOP_BELOW_DEDUCTIBLE = "ERR_OOP_BELOW_DEDUCTIBLE"

    # Generic field validation — PRD §2.8 rung 16.
    ERR_VALIDATION = "ERR_VALIDATION"


# PRD §5 Error Code Catalogue — HTTP status per error_id.
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_RESOURCE_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_MEMBER_NOT_ACTIVE: 409,
    ApiErrorId.ERR_REFILL_TOO_SOON: 409,
    ApiErrorId.ERR_COPAY_CARD_EXHAUSTED: 409,
    ApiErrorId.ERR_PA_REQUIRED: 422,
    ApiErrorId.ERR_PA_DENIED: 422,
    ApiErrorId.ERR_PA_REVOKED: 422,
    ApiErrorId.ERR_PA_EXPIRED: 422,
    ApiErrorId.ERR_PA_MISMATCH: 422,
    ApiErrorId.ERR_PA_REVISION_LIMIT: 422,
    ApiErrorId.ERR_STEP_THERAPY_NOT_SATISFIED: 422,
    ApiErrorId.ERR_SPECIALTY_CHANNEL_REQUIRED: 422,
    ApiErrorId.ERR_CHANNEL_DAYS_SUPPLY_MISMATCH: 422,
    ApiErrorId.ERR_DRUG_NOT_ON_FORMULARY: 422,
    ApiErrorId.ERR_COPAY_CARD_MISMATCH: 422,
    ApiErrorId.ERR_CLAWBACK_WINDOW_EXPIRED: 422,
    ApiErrorId.ERR_OOP_BELOW_DEDUCTIBLE: 422,
    ApiErrorId.ERR_VALIDATION: 422,
}


# Register with the framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
