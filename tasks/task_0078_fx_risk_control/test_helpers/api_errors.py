"""Error IDs and HTTP status mapping (PRD §5).

After definition the mapping is registered with the framework so
validate_error() can auto-check HTTP status codes on every call.
"""
from __future__ import annotations
from enum import Enum

from prd_bench_local_runner.testing.validators import (
    set_error_http_status_map,
)


class ApiErrorId(str, Enum):
    # ---- auth / authz (PRD §2.1) ----
    ERR_AUTH_REQUIRED = "ERR_AUTH_REQUIRED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_SEGREGATION_VIOLATION = "ERR_SEGREGATION_VIOLATION"

    # ---- existence ----
    ERR_NOT_FOUND = "ERR_NOT_FOUND"

    # ---- state-machine preconditions ----
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_REQUEST_ALREADY_DECIDED = "ERR_REQUEST_ALREADY_DECIDED"

    # ---- concurrency / OCC ----
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"

    # ---- fiscal & business ----
    ERR_LIMIT_BREACH = "ERR_LIMIT_BREACH"
    ERR_COUNTERPARTY_LIMIT_BREACH = "ERR_COUNTERPARTY_LIMIT_BREACH"
    ERR_COUNTERPARTY_WATCHLIST = "ERR_COUNTERPARTY_WATCHLIST"
    ERR_TRADER_SUSPENDED = "ERR_TRADER_SUSPENDED"

    # ---- temporal / format ----
    ERR_EXPIRES_IN_PAST = "ERR_EXPIRES_IN_PAST"
    ERR_INVALID_PAIR_FORMAT = "ERR_INVALID_PAIR_FORMAT"
    ERR_INVALID_PAGINATION = "ERR_INVALID_PAGINATION"

    # ---- idempotency ----
    ERR_IDEMPOTENCY_REPLAY = "ERR_IDEMPOTENCY_REPLAY"

    # ---- generic validation ----
    ERR_VALIDATION = "ERR_VALIDATION"
    ERR_INVALID_STOPLOSS_MODE = "ERR_INVALID_STOPLOSS_MODE"


# Per PRD §5 — Error Code Catalogue.
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_AUTH_REQUIRED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_SEGREGATION_VIOLATION: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_REQUEST_ALREADY_DECIDED: 409,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_LIMIT_BREACH: 409,
    ApiErrorId.ERR_COUNTERPARTY_LIMIT_BREACH: 409,
    ApiErrorId.ERR_COUNTERPARTY_WATCHLIST: 409,
    ApiErrorId.ERR_TRADER_SUSPENDED: 409,
    ApiErrorId.ERR_EXPIRES_IN_PAST: 422,
    ApiErrorId.ERR_INVALID_PAIR_FORMAT: 422,
    ApiErrorId.ERR_INVALID_PAGINATION: 422,
    ApiErrorId.ERR_IDEMPOTENCY_REPLAY: 200,
    ApiErrorId.ERR_VALIDATION: 422,
    ApiErrorId.ERR_INVALID_STOPLOSS_MODE: 422,
}


# Register with framework so validate_error() can cross-check HTTP statuses.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()}
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
