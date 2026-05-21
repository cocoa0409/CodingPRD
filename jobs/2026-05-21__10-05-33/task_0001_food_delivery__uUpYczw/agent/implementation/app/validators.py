"""Input shape validators raising ERR_VALIDATION on failure."""
from __future__ import annotations

from typing import Any

from .errors import ApiError


def require(body: dict, key: str) -> Any:
    if key not in body or body[key] is None:
        raise ApiError("ERR_VALIDATION", f"Missing required field: {key}")
    return body[key]


def opt_int(body: dict, key: str) -> int | None:
    v = body.get(key)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", f"{key} must be an integer")
    return v


def req_int(body: dict, key: str) -> int:
    v = require(body, key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", f"{key} must be an integer")
    return v


def req_str(body: dict, key: str) -> str:
    v = require(body, key)
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", f"{key} must be a string")
    return v


def opt_str(body: dict, key: str) -> str | None:
    v = body.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", f"{key} must be a string")
    return v


def req_number(body: dict, key: str) -> float:
    v = require(body, key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", f"{key} must be a number")
    return float(v)


def opt_number(body: dict, key: str) -> float | None:
    v = body.get(key)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", f"{key} must be a number")
    return float(v)


def opt_bool(body: dict, key: str) -> bool | None:
    v = body.get(key)
    if v is None:
        return None
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", f"{key} must be a boolean")
    return v
