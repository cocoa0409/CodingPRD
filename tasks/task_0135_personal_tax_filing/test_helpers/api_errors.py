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
    # Auth — PRD §2.1 / §2.10
    ERR_AUTH_REQUIRED = "ERR_AUTH_REQUIRED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"

    # Existence — PRD §2.8 / §2.10
    ERR_TAXPAYER_NOT_FOUND = "ERR_TAXPAYER_NOT_FOUND"
    ERR_RETURN_NOT_FOUND = "ERR_RETURN_NOT_FOUND"
    ERR_RESOURCE_NOT_FOUND = "ERR_RESOURCE_NOT_FOUND"

    # State / lifecycle — PRD §2.7 / §2.10 / §3
    ERR_TAXPAYER_LOCKED = "ERR_TAXPAYER_LOCKED"
    ERR_INVALID_STATE = "ERR_INVALID_STATE"

    # Amendment business referential — PRD §3.9
    ERR_AMENDMENT_NOT_ALLOWED = "ERR_AMENDMENT_NOT_ALLOWED"
    ERR_AMENDMENT_ALREADY_OPEN = "ERR_AMENDMENT_ALREADY_OPEN"

    # Income document / Schedule input — PRD §3.2 / §3.3
    ERR_QUALIFIED_DIV_EXCEEDS_ORDINARY = "ERR_QUALIFIED_DIV_EXCEEDS_ORDINARY"
    ERR_INCOME_DOC_INVALID = "ERR_INCOME_DOC_INVALID"
    ERR_SALT_CAP_EXCEEDED = "ERR_SALT_CAP_EXCEEDED"

    # TaxReturn / TaxCredit business constraints — PRD §3.1 / §3.4
    ERR_QUALIFYING_CHILDREN_EXCEED_DEPENDENTS = (
        "ERR_QUALIFYING_CHILDREN_EXCEED_DEPENDENTS"
    )
    ERR_CREDIT_INELIGIBLE = "ERR_CREDIT_INELIGIBLE"
    ERR_DUPLICATE_CREDIT = "ERR_DUPLICATE_CREDIT"
    ERR_DUPLICATE_SCHEDULE = "ERR_DUPLICATE_SCHEDULE"
    ERR_DUPLICATE_RETURN = "ERR_DUPLICATE_RETURN"

    # Estimated payments — PRD §3.10
    ERR_PAYMENT_DATE_PAST = "ERR_PAYMENT_DATE_PAST"
    ERR_PAYMENT_CANNOT_CANCEL = "ERR_PAYMENT_CANNOT_CANCEL"

    # OCC — PRD §2.6
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"

    # Generic input validation — PRD §2.10
    ERR_INVALID_INPUT = "ERR_INVALID_INPUT"


# PRD §5 — Error Code Catalogue (HTTP status mapping).
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_AUTH_REQUIRED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_TAXPAYER_NOT_FOUND: 404,
    ApiErrorId.ERR_RETURN_NOT_FOUND: 404,
    ApiErrorId.ERR_RESOURCE_NOT_FOUND: 404,
    ApiErrorId.ERR_TAXPAYER_LOCKED: 409,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_AMENDMENT_NOT_ALLOWED: 409,
    ApiErrorId.ERR_AMENDMENT_ALREADY_OPEN: 409,
    ApiErrorId.ERR_QUALIFIED_DIV_EXCEEDS_ORDINARY: 422,
    ApiErrorId.ERR_INCOME_DOC_INVALID: 422,
    ApiErrorId.ERR_SALT_CAP_EXCEEDED: 422,
    ApiErrorId.ERR_QUALIFYING_CHILDREN_EXCEED_DEPENDENTS: 422,
    ApiErrorId.ERR_CREDIT_INELIGIBLE: 422,
    ApiErrorId.ERR_DUPLICATE_CREDIT: 409,
    ApiErrorId.ERR_DUPLICATE_SCHEDULE: 409,
    ApiErrorId.ERR_DUPLICATE_RETURN: 409,
    ApiErrorId.ERR_PAYMENT_DATE_PAST: 422,
    ApiErrorId.ERR_PAYMENT_CANNOT_CANCEL: 409,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_INVALID_INPUT: 422,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
