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
    # PRD §5 — validation / structural input
    ERR_VALIDATION = "ERR_VALIDATION"

    # PRD §2.1 — authentication / authorisation
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"

    # PRD §2.7 — existence
    ERR_NOT_FOUND = "ERR_NOT_FOUND"

    # PRD §2.9 — state
    ERR_INVALID_STATE = "ERR_INVALID_STATE"

    # PRD §3.2 / §3.6 — safety
    ERR_ALLERGEN_BLOCK = "ERR_ALLERGEN_BLOCK"
    ERR_DOCTOR_NOTE_REQUIRED = "ERR_DOCTOR_NOTE_REQUIRED"
    ERR_DUPLICATE_ALLERGEN = "ERR_DUPLICATE_ALLERGEN"

    # PRD §3.6 — meal serving / fiscal
    ERR_MEAL_ALREADY_SERVED_TODAY = "ERR_MEAL_ALREADY_SERVED_TODAY"
    ERR_PREPAID_BALANCE_INSUFFICIENT = "ERR_PREPAID_BALANCE_INSUFFICIENT"

    # PRD §3.7 — USDA claims
    ERR_CLAIM_PERIOD_OVERLAP = "ERR_CLAIM_PERIOD_OVERLAP"

    # PRD §3.4 / §3.7 — segregation of duties
    ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"

    # PRD §3.5 — auto-renewal
    ERR_RENEWAL_INELIGIBLE = "ERR_RENEWAL_INELIGIBLE"

    # PRD §3.6 — refunds
    ERR_REFUND_MISMATCH = "ERR_REFUND_MISMATCH"

    # PRD §3.1 — parent email uniqueness
    ERR_PARENT_EMAIL_TAKEN = "ERR_PARENT_EMAIL_TAKEN"

    # PRD §3.3 — menu item retirement guard
    ERR_MENU_ITEM_IN_USE = "ERR_MENU_ITEM_IN_USE"

    # PRD §2.6 — optimistic concurrency
    ERR_VERSION_MISMATCH = "ERR_VERSION_MISMATCH"


HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_VALIDATION: 422,
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_ALLERGEN_BLOCK: 409,
    ApiErrorId.ERR_DOCTOR_NOTE_REQUIRED: 422,
    ApiErrorId.ERR_DUPLICATE_ALLERGEN: 409,
    ApiErrorId.ERR_MEAL_ALREADY_SERVED_TODAY: 409,
    ApiErrorId.ERR_PREPAID_BALANCE_INSUFFICIENT: 409,
    ApiErrorId.ERR_CLAIM_PERIOD_OVERLAP: 409,
    ApiErrorId.ERR_SEGREGATION_OF_DUTIES: 403,
    ApiErrorId.ERR_RENEWAL_INELIGIBLE: 422,
    ApiErrorId.ERR_REFUND_MISMATCH: 422,
    ApiErrorId.ERR_PARENT_EMAIL_TAKEN: 409,
    ApiErrorId.ERR_MENU_ITEM_IN_USE: 409,
    ApiErrorId.ERR_VERSION_MISMATCH: 412,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
