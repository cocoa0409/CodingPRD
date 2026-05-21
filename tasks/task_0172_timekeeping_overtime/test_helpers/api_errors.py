"""Error IDs and HTTP status mapping — PRD §5.

The mapping is registered with the framework at import time so
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
    ERR_INVALID_ROLE = "ERR_INVALID_ROLE"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    # Existence — PRD §2.8
    ERR_RESOURCE_NOT_FOUND = "ERR_RESOURCE_NOT_FOUND"
    # Shift state — PRD §3.2
    ERR_SHIFT_INVALID_STATE = "ERR_SHIFT_INVALID_STATE"
    ERR_SHIFT_ALREADY_OPEN = "ERR_SHIFT_ALREADY_OPEN"
    # TimeEdit state — PRD §3.5
    ERR_TIME_EDIT_NOT_PENDING = "ERR_TIME_EDIT_NOT_PENDING"
    # Workweek — PRD §3.6
    ERR_WORKWEEK_LOCKED = "ERR_WORKWEEK_LOCKED"
    # Business-safety — PRD §2.1, §3.5
    ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
    ERR_FRAUD_REQUIRES_ADMIN = "ERR_FRAUD_REQUIRES_ADMIN"
    ERR_EXEMPT_NOT_ELIGIBLE = "ERR_EXEMPT_NOT_ELIGIBLE"
    # Punch ordering / window / meal — PRD §3.2
    ERR_PUNCH_OUT_OF_ORDER = "ERR_PUNCH_OUT_OF_ORDER"
    ERR_MEAL_BREAK_DUPLICATE = "ERR_MEAL_BREAK_DUPLICATE"
    ERR_PUNCH_OUTSIDE_WINDOW = "ERR_PUNCH_OUTSIDE_WINDOW"
    # TimeEdit range — PRD §3.5
    ERR_TIME_EDIT_OUT_OF_RANGE = "ERR_TIME_EDIT_OUT_OF_RANGE"
    # Workweek anchor — PRD §3.6
    ERR_WORKWEEK_BAD_ANCHOR = "ERR_WORKWEEK_BAD_ANCHOR"
    # Tipped-wage validation — PRD §3.1, §3.7
    ERR_TIPPED_FIELDS_MISMATCH = "ERR_TIPPED_FIELDS_MISMATCH"
    ERR_TIPS_NOT_APPLICABLE = "ERR_TIPS_NOT_APPLICABLE"
    ERR_BELOW_MINIMUM_WAGE = "ERR_BELOW_MINIMUM_WAGE"
    # OCC — PRD §2.5
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
    # Idempotency — PRD §2.10, §3.5
    ERR_DUPLICATE_IDEMPOTENCY_KEY = "ERR_DUPLICATE_IDEMPOTENCY_KEY"
    # Schema — PRD §2.9
    ERR_INVALID_INPUT = "ERR_INVALID_INPUT"


# PRD §5 — Error Code Catalogue
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_AUTH_REQUIRED: 401,
    ApiErrorId.ERR_INVALID_ROLE: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_RESOURCE_NOT_FOUND: 404,
    ApiErrorId.ERR_SHIFT_INVALID_STATE: 409,
    ApiErrorId.ERR_SHIFT_ALREADY_OPEN: 409,
    ApiErrorId.ERR_TIME_EDIT_NOT_PENDING: 409,
    ApiErrorId.ERR_WORKWEEK_LOCKED: 409,
    ApiErrorId.ERR_SEGREGATION_OF_DUTIES: 403,
    ApiErrorId.ERR_FRAUD_REQUIRES_ADMIN: 403,
    ApiErrorId.ERR_EXEMPT_NOT_ELIGIBLE: 422,
    ApiErrorId.ERR_PUNCH_OUT_OF_ORDER: 422,
    ApiErrorId.ERR_MEAL_BREAK_DUPLICATE: 409,
    ApiErrorId.ERR_PUNCH_OUTSIDE_WINDOW: 422,
    ApiErrorId.ERR_TIME_EDIT_OUT_OF_RANGE: 422,
    ApiErrorId.ERR_WORKWEEK_BAD_ANCHOR: 422,
    ApiErrorId.ERR_TIPPED_FIELDS_MISMATCH: 422,
    ApiErrorId.ERR_TIPS_NOT_APPLICABLE: 422,
    ApiErrorId.ERR_BELOW_MINIMUM_WAGE: 422,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_DUPLICATE_IDEMPOTENCY_KEY: 409,
    ApiErrorId.ERR_INVALID_INPUT: 422,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
