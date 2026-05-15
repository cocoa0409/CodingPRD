"""Error IDs and HTTP status mapping (PRD §5).

After definition the mapping is registered with the framework so
validate_error() can auto-check HTTP status codes.
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

    # ---- existence ----
    ERR_NOT_FOUND = "ERR_NOT_FOUND"

    # ---- state-machine preconditions ----
    ERR_INVALID_STATE = "ERR_INVALID_STATE"

    # ---- concurrency / OCC ----
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"

    # ---- safety gating ----
    ERR_BATTERY_RECALLED = "ERR_BATTERY_RECALLED"
    ERR_INCOMPATIBLE_MODEL = "ERR_INCOMPATIBLE_MODEL"

    # ---- reservation temporal / constraint ----
    ERR_INVALID_TIME_SLOT = "ERR_INVALID_TIME_SLOT"
    ERR_RESERVATION_OVERLAP_MEMBER = "ERR_RESERVATION_OVERLAP_MEMBER"
    ERR_STATION_CAPACITY_FULL = "ERR_STATION_CAPACITY_FULL"
    ERR_NO_COMPATIBLE_BATTERY = "ERR_NO_COMPATIBLE_BATTERY"
    ERR_MEMBER_BLOCKED = "ERR_MEMBER_BLOCKED"

    # ---- billing / refund ----
    ERR_REFUND_EXCEEDS_PAID = "ERR_REFUND_EXCEEDS_PAID"

    # ---- dispatch ----
    ERR_BATTERY_NOT_IDLE = "ERR_BATTERY_NOT_IDLE"
    ERR_INVALID_DISPATCH = "ERR_INVALID_DISPATCH"

    # ---- generic ----
    ERR_INVALID_PAGINATION = "ERR_INVALID_PAGINATION"
    ERR_DUPLICATE_RESOURCE = "ERR_DUPLICATE_RESOURCE"
    ERR_INVALID_INPUT = "ERR_INVALID_INPUT"


# PRD §5 — Error Code Catalogue table
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_AUTH_REQUIRED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_BATTERY_RECALLED: 409,
    ApiErrorId.ERR_INCOMPATIBLE_MODEL: 422,
    ApiErrorId.ERR_INVALID_TIME_SLOT: 422,
    ApiErrorId.ERR_RESERVATION_OVERLAP_MEMBER: 409,
    ApiErrorId.ERR_STATION_CAPACITY_FULL: 409,
    ApiErrorId.ERR_NO_COMPATIBLE_BATTERY: 409,
    ApiErrorId.ERR_MEMBER_BLOCKED: 403,
    ApiErrorId.ERR_REFUND_EXCEEDS_PAID: 422,
    ApiErrorId.ERR_BATTERY_NOT_IDLE: 409,
    ApiErrorId.ERR_INVALID_DISPATCH: 422,
    ApiErrorId.ERR_INVALID_PAGINATION: 422,
    ApiErrorId.ERR_DUPLICATE_RESOURCE: 409,
    ApiErrorId.ERR_INVALID_INPUT: 422,
}


# Register with framework so validate_error() can cross-check HTTP statuses.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()}
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
