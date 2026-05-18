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
    # Auth & RBAC — PRD §2.1
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"

    # Existence — PRD §2.5
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"

    # Validation — PRD §5
    ERR_VALIDATION = "ERR_VALIDATION"

    # Account / state — PRD §3.1 / §3.4
    ERR_ACCOUNT_CLOSED = "ERR_ACCOUNT_CLOSED"
    ERR_INVALID_STATE = "ERR_INVALID_STATE"

    # Activation business rules — PRD §3.2
    ERR_CATEGORY_NOT_ACTIVATABLE = "ERR_CATEGORY_NOT_ACTIVATABLE"
    ERR_ACTIVATION_WINDOW_CLOSED = "ERR_ACTIVATION_WINDOW_CLOSED"
    ERR_ACTIVATION_ALREADY_EXISTS = "ERR_ACTIVATION_ALREADY_EXISTS"

    # Transfer business rules — PRD §3.7
    ERR_INVALID_TRANSFER_INCREMENT = "ERR_INVALID_TRANSFER_INCREMENT"
    ERR_PARTNER_INACTIVE = "ERR_PARTNER_INACTIVE"

    # Balance / redemption — PRD §3.6 / §3.7
    ERR_INSUFFICIENT_POINTS = "ERR_INSUFFICIENT_POINTS"
    ERR_BELOW_MINIMUM_REDEMPTION = "ERR_BELOW_MINIMUM_REDEMPTION"
    ERR_INVALID_REDEMPTION_BODY = "ERR_INVALID_REDEMPTION_BODY"

    # Refund business rules — PRD §3.4
    ERR_REFUND_MISMATCH = "ERR_REFUND_MISMATCH"
    ERR_PARTIAL_REFUND_DISALLOWED = "ERR_PARTIAL_REFUND_DISALLOWED"


# PRD §5 Error Code Catalogue — HTTP status table.
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_REFERENCE_NOT_FOUND: 422,
    ApiErrorId.ERR_VALIDATION: 422,
    ApiErrorId.ERR_ACCOUNT_CLOSED: 409,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_CATEGORY_NOT_ACTIVATABLE: 422,
    ApiErrorId.ERR_ACTIVATION_WINDOW_CLOSED: 422,
    ApiErrorId.ERR_ACTIVATION_ALREADY_EXISTS: 409,
    ApiErrorId.ERR_INVALID_TRANSFER_INCREMENT: 422,
    ApiErrorId.ERR_PARTNER_INACTIVE: 422,
    ApiErrorId.ERR_INSUFFICIENT_POINTS: 422,
    ApiErrorId.ERR_BELOW_MINIMUM_REDEMPTION: 422,
    ApiErrorId.ERR_INVALID_REDEMPTION_BODY: 422,
    ApiErrorId.ERR_REFUND_MISMATCH: 422,
    ApiErrorId.ERR_PARTIAL_REFUND_DISALLOWED: 422,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
