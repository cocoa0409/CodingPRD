"""Error IDs and HTTP status mapping — PRD §5.

Mapping is registered with the framework at import time so
`validate_error()` cross-checks HTTP status codes against the catalog
without each test passing them explicitly.
"""
from __future__ import annotations

from enum import Enum

from prd_bench_local_runner.testing.validators import (
    set_error_http_status_map,
)


class ApiErrorId(str, Enum):
    # Auth — PRD §2.1
    ERR_MISSING_AUTH = "ERR_MISSING_AUTH"
    ERR_INVALID_ROLE = "ERR_INVALID_ROLE"
    # Existence — PRD §2.5
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"
    # State — PRD §2.7, §3
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_CROSS_ENTITY_STATE = "ERR_CROSS_ENTITY_STATE"
    # Business safety — PRD §2.7
    ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
    ERR_RECEIPT_ALREADY_USED = "ERR_RECEIPT_ALREADY_USED"
    # Business referential — PRD §2.7
    ERR_CARD_TRIP_MISMATCH = "ERR_CARD_TRIP_MISMATCH"
    ERR_EXPENSE_OUTSIDE_TRIP_WINDOW = "ERR_EXPENSE_OUTSIDE_TRIP_WINDOW"
    # Business constraint — PRD §2.7
    ERR_PER_DIEM_UNAVAILABLE = "ERR_PER_DIEM_UNAVAILABLE"
    ERR_RECEIPT_REQUIRED = "ERR_RECEIPT_REQUIRED"
    ERR_CATEGORY_FIELD_MISSING = "ERR_CATEGORY_FIELD_MISSING"
    # Business fiscal — PRD §2.7, §3.2
    ERR_CARD_LIMIT_EXCEEDS_BUDGET = "ERR_CARD_LIMIT_EXCEEDS_BUDGET"
    ERR_CARD_LIMIT_EXCEEDED = "ERR_CARD_LIMIT_EXCEEDED"
    # OOP chain — PRD §3.5
    ERR_OOP_WRONG_APPROVER_ROLE = "ERR_OOP_WRONG_APPROVER_ROLE"
    ERR_OOP_DUPLICATE_APPROVER = "ERR_OOP_DUPLICATE_APPROVER"
    # OCC — PRD §2.4
    ERR_STALE_VERSION = "ERR_STALE_VERSION"
    # Race outcomes — PRD §2.10
    ERR_REPORT_ALREADY_CLAIMED = "ERR_REPORT_ALREADY_CLAIMED"
    # Generic validation — PRD §2.7
    ERR_VALIDATION = "ERR_VALIDATION"


# PRD §5 Error Code Catalogue
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_MISSING_AUTH: 401,
    ApiErrorId.ERR_INVALID_ROLE: 401,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_REFERENCE_NOT_FOUND: 422,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_CROSS_ENTITY_STATE: 409,
    ApiErrorId.ERR_SEGREGATION_OF_DUTIES: 403,
    ApiErrorId.ERR_RECEIPT_ALREADY_USED: 409,
    ApiErrorId.ERR_CARD_TRIP_MISMATCH: 422,
    ApiErrorId.ERR_EXPENSE_OUTSIDE_TRIP_WINDOW: 422,
    ApiErrorId.ERR_PER_DIEM_UNAVAILABLE: 422,
    ApiErrorId.ERR_RECEIPT_REQUIRED: 422,
    ApiErrorId.ERR_CATEGORY_FIELD_MISSING: 422,
    ApiErrorId.ERR_CARD_LIMIT_EXCEEDS_BUDGET: 422,
    ApiErrorId.ERR_CARD_LIMIT_EXCEEDED: 409,
    ApiErrorId.ERR_OOP_WRONG_APPROVER_ROLE: 403,
    ApiErrorId.ERR_OOP_DUPLICATE_APPROVER: 403,
    ApiErrorId.ERR_STALE_VERSION: 409,
    ApiErrorId.ERR_REPORT_ALREADY_CLAIMED: 409,
    ApiErrorId.ERR_VALIDATION: 400,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
