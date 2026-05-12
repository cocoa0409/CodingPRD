"""Error IDs and HTTP status mapping (PRD section 5).

Registered with the framework so validate_error() can auto-check status
codes against the PRD catalogue.
"""
from __future__ import annotations

from enum import Enum

from prd_bench_local_runner.testing.validators import (
    set_error_http_status_map,
)


class ApiErrorId(str, Enum):
    # --- Auth / authz (PRD section 2.1, section 5) ---
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"

    # --- Not-found / shape (PRD section 2.6, section 5) ---
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_BAD_REQUEST = "ERR_BAD_REQUEST"

    # --- State (PRD section 2.7, section 5) ---
    ERR_INVALID_STATE = "ERR_INVALID_STATE"

    # --- Robot business-safety / connectivity / availability ---
    ERR_ROBOT_FAULTED = "ERR_ROBOT_FAULTED"
    ERR_ROBOT_OFFLINE = "ERR_ROBOT_OFFLINE"
    ERR_ROBOT_BUSY = "ERR_ROBOT_BUSY"
    ERR_BATTERY_LOW = "ERR_BATTERY_LOW"
    ERR_NO_PATH = "ERR_NO_PATH"
    ERR_RIGHT_OF_WAY_MISSING = "ERR_RIGHT_OF_WAY_MISSING"
    ERR_CHARGER_UNAVAILABLE = "ERR_CHARGER_UNAVAILABLE"

    # --- Slot reservations ---
    ERR_SLOT_ALREADY_RESERVED = "ERR_SLOT_ALREADY_RESERVED"
    ERR_SLOT_TIME_INVALID = "ERR_SLOT_TIME_INVALID"

    # --- Split / merge ---
    ERR_SPLIT_NOT_APPLICABLE = "ERR_SPLIT_NOT_APPLICABLE"
    ERR_MERGE_INCOMPATIBLE = "ERR_MERGE_INCOMPATIBLE"

    # --- Dependency / assignment / rollback ---
    ERR_HAS_DEPENDENCIES = "ERR_HAS_DEPENDENCIES"
    ERR_TASK_ALREADY_ASSIGNED = "ERR_TASK_ALREADY_ASSIGNED"
    ERR_ROLLBACK_LIMIT_REACHED = "ERR_ROLLBACK_LIMIT_REACHED"

    # --- Time / map / isolation ---
    ERR_CLOCK_BACKWARDS = "ERR_CLOCK_BACKWARDS"
    ERR_OBSTACLE_BLOCKING = "ERR_OBSTACLE_BLOCKING"
    ERR_ISOLATION_VIOLATION = "ERR_ISOLATION_VIOLATION"


HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_BAD_REQUEST: 400,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_ROBOT_FAULTED: 409,
    ApiErrorId.ERR_ROBOT_OFFLINE: 409,
    ApiErrorId.ERR_ROBOT_BUSY: 409,
    ApiErrorId.ERR_BATTERY_LOW: 409,
    ApiErrorId.ERR_NO_PATH: 409,
    ApiErrorId.ERR_RIGHT_OF_WAY_MISSING: 409,
    ApiErrorId.ERR_CHARGER_UNAVAILABLE: 409,
    ApiErrorId.ERR_SLOT_ALREADY_RESERVED: 409,
    ApiErrorId.ERR_SLOT_TIME_INVALID: 422,
    ApiErrorId.ERR_SPLIT_NOT_APPLICABLE: 422,
    ApiErrorId.ERR_MERGE_INCOMPATIBLE: 422,
    ApiErrorId.ERR_HAS_DEPENDENCIES: 409,
    ApiErrorId.ERR_TASK_ALREADY_ASSIGNED: 409,
    ApiErrorId.ERR_ROLLBACK_LIMIT_REACHED: 409,
    ApiErrorId.ERR_CLOCK_BACKWARDS: 422,
    ApiErrorId.ERR_OBSTACLE_BLOCKING: 409,
    ApiErrorId.ERR_ISOLATION_VIOLATION: 409,
}


# Register with framework so validate_error() can cross-check HTTP statuses.
set_error_http_status_map({k.value: v for k, v in HTTP_STATUS_CODES.items()})


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
