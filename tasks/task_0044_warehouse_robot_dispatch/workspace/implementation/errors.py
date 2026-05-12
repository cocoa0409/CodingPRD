"""Error definitions for warehouse robot dispatch API."""
from __future__ import annotations


class APIError(Exception):
    """Base error with error_id, http_status, and message."""

    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue — error_id → http_status
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_BAD_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_ROBOT_FAULTED": 409,
    "ERR_ROBOT_OFFLINE": 409,
    "ERR_ROBOT_BUSY": 409,
    "ERR_BATTERY_LOW": 409,
    "ERR_NO_PATH": 409,
    "ERR_RIGHT_OF_WAY_MISSING": 409,
    "ERR_CHARGER_UNAVAILABLE": 409,
    "ERR_SLOT_ALREADY_RESERVED": 409,
    "ERR_SLOT_TIME_INVALID": 422,
    "ERR_SPLIT_NOT_APPLICABLE": 422,
    "ERR_MERGE_INCOMPATIBLE": 422,
    "ERR_HAS_DEPENDENCIES": 409,
    "ERR_TASK_ALREADY_ASSIGNED": 409,
    "ERR_CLOCK_BACKWARDS": 422,
    "ERR_ROLLBACK_LIMIT_REACHED": 409,
    "ERR_OBSTACLE_BLOCKING": 409,
    "ERR_ISOLATION_VIOLATION": 409,
}


def raise_error(error_id: str, message: str = ""):
    http = ERROR_CATALOG.get(error_id, 500)
    raise APIError(error_id, http, message or error_id)
