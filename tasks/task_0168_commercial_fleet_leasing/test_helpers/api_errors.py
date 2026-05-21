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
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    # Existence — PRD §2.5
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    # State checks — PRD §2.11 / §3
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
    # Input shape — PRD §5
    ERR_VALIDATION = "ERR_VALIDATION"
    # Business — PRD §3
    ERR_VEHICLE_ALREADY_ALLOCATED = "ERR_VEHICLE_ALREADY_ALLOCATED"
    ERR_OPEN_COLLISION_BLOCKS_RETURN = "ERR_OPEN_COLLISION_BLOCKS_RETURN"
    ERR_CARD_INACTIVE = "ERR_CARD_INACTIVE"
    ERR_QUARTER_CLOSED = "ERR_QUARTER_CLOSED"
    ERR_QUARTER_NOT_READY = "ERR_QUARTER_NOT_READY"
    ERR_REVISION_LIMIT_REACHED = "ERR_REVISION_LIMIT_REACHED"
    ERR_CARD_LIMIT_EXCEEDED = "ERR_CARD_LIMIT_EXCEEDED"
    ERR_DISPUTE_WINDOW_CLOSED = "ERR_DISPUTE_WINDOW_CLOSED"
    ERR_DUPLICATE_SETTLEMENT_PERIOD = "ERR_DUPLICATE_SETTLEMENT_PERIOD"
    ERR_ACTUAL_COST_REQUIRED = "ERR_ACTUAL_COST_REQUIRED"
    ERR_VEHICLE_NOT_RETURNABLE = "ERR_VEHICLE_NOT_RETURNABLE"


# PRD §5 — Error Code Catalogue
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_AUTH_REQUIRED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_VALIDATION: 422,
    ApiErrorId.ERR_VEHICLE_ALREADY_ALLOCATED: 409,
    ApiErrorId.ERR_OPEN_COLLISION_BLOCKS_RETURN: 409,
    ApiErrorId.ERR_CARD_INACTIVE: 409,
    ApiErrorId.ERR_QUARTER_CLOSED: 409,
    ApiErrorId.ERR_QUARTER_NOT_READY: 409,
    ApiErrorId.ERR_REVISION_LIMIT_REACHED: 422,
    ApiErrorId.ERR_CARD_LIMIT_EXCEEDED: 422,
    ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED: 409,
    ApiErrorId.ERR_DUPLICATE_SETTLEMENT_PERIOD: 409,
    ApiErrorId.ERR_ACTUAL_COST_REQUIRED: 422,
    ApiErrorId.ERR_VEHICLE_NOT_RETURNABLE: 409,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
