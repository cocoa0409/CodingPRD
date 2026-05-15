"""Shared input-validation helpers — raise ApiError with the correct error_id."""
from __future__ import annotations

from typing import Any

from ..errors import ApiError


def require_field(body: dict[str, Any], field: str) -> Any:
    if field not in body:
        raise ApiError("ERR_BAD_REQUEST", f"Missing required field: {field}")
    return body[field]


def require_int(value: Any, field: str, min_value: int | None = None, max_value: int | None = None) -> int:
    if isinstance(value, bool):
        raise ApiError("ERR_BAD_REQUEST", f"Field {field} must be an integer.")
    if not isinstance(value, int):
        raise ApiError("ERR_BAD_REQUEST", f"Field {field} must be an integer.")
    if min_value is not None and value < min_value:
        raise ApiError("ERR_BAD_REQUEST", f"Field {field} below min {min_value}: {value}")
    if max_value is not None and value > max_value:
        raise ApiError("ERR_BAD_REQUEST", f"Field {field} above max {max_value}: {value}")
    return value


def require_str(value: Any, field: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ApiError("ERR_BAD_REQUEST", f"Field {field} must be a string.")
    if not allow_empty and not value.strip():
        raise ApiError("ERR_BAD_REQUEST", f"Field {field} must be non-empty.")
    return value


def require_in(value: Any, field: str, choices: set) -> Any:
    if value not in choices:
        raise ApiError("ERR_BAD_REQUEST", f"Field {field} must be one of {sorted(choices)}.")
    return value


def require_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ApiError("ERR_BAD_REQUEST", f"Field {field} must be a number.")
    if isinstance(value, (int, float)):
        return float(value)
    raise ApiError("ERR_BAD_REQUEST", f"Field {field} must be a number.")
