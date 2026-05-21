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
    # --- Auth / RBAC --- PRD §2.1, §5
    ERR_AUTH_MISSING = "ERR_AUTH_MISSING"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_NOT_OWNER = "ERR_NOT_OWNER"

    # --- Existence --- PRD §2.8, §5
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"

    # --- State / concurrency --- PRD §2.9, §2.10, §3.x, §5
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_DISPUTE_ALREADY_EXISTS = "ERR_DISPUTE_ALREADY_EXISTS"
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
    ERR_NO_DRIVERS_AVAILABLE = "ERR_NO_DRIVERS_AVAILABLE"

    # --- Business constraint (422) --- PRD §3.x, §5
    ERR_NOT_AIRPORT_GRID = "ERR_NOT_AIRPORT_GRID"
    ERR_DRIVER_NOT_IN_GRID = "ERR_DRIVER_NOT_IN_GRID"
    ERR_RUSH_HOUR_OVERLAP = "ERR_RUSH_HOUR_OVERLAP"
    ERR_QUEST_WINDOW_OVERLAP = "ERR_QUEST_WINDOW_OVERLAP"
    ERR_REFUND_EXCEEDS_FARE = "ERR_REFUND_EXCEEDS_FARE"
    ERR_REFUND_EXCEEDS_REQUEST = "ERR_REFUND_EXCEEDS_REQUEST"

    # --- Generic shape / range --- PRD §2.9, §5
    ERR_INVALID_INPUT = "ERR_INVALID_INPUT"


# PRD §5 Error Code Catalogue — HTTP status per error_id.
HTTP_STATUS_CODES: dict = {
    # 401
    ApiErrorId.ERR_AUTH_MISSING: 401,
    # 403
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_OWNER: 403,
    # 404
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_REFERENCE_NOT_FOUND: 404,
    # 409
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_DISPUTE_ALREADY_EXISTS: 409,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_NO_DRIVERS_AVAILABLE: 409,
    # 422
    ApiErrorId.ERR_NOT_AIRPORT_GRID: 422,
    ApiErrorId.ERR_DRIVER_NOT_IN_GRID: 422,
    ApiErrorId.ERR_RUSH_HOUR_OVERLAP: 422,
    ApiErrorId.ERR_QUEST_WINDOW_OVERLAP: 422,
    ApiErrorId.ERR_REFUND_EXCEEDS_FARE: 422,
    ApiErrorId.ERR_REFUND_EXCEEDS_REQUEST: 422,
    ApiErrorId.ERR_INVALID_INPUT: 422,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
