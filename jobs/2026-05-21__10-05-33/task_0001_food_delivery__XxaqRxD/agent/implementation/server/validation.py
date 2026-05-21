"""Input validation helpers shared across routes."""
from __future__ import annotations

from typing import Any

from .errors import ApiError


def ensure_dict(body: Any) -> dict:
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "request body must be a JSON object")
    return body


def require_str(d: dict, key: str, *, max_len: int | None = None, allow_empty: bool = False) -> str:
    v = d.get(key)
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", f"{key} must be a string")
    if not allow_empty and not v:
        raise ApiError("ERR_VALIDATION", f"{key} must not be empty")
    if max_len is not None and len(v) > max_len:
        raise ApiError("ERR_VALIDATION", f"{key} too long")
    return v


def require_int(d: dict, key: str, *, min_val: int | None = None, max_val: int | None = None) -> int:
    v = d.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", f"{key} must be an integer")
    if min_val is not None and v < min_val:
        raise ApiError("ERR_VALIDATION", f"{key} must be >= {min_val}")
    if max_val is not None and v > max_val:
        raise ApiError("ERR_VALIDATION", f"{key} must be <= {max_val}")
    return v


def require_num(d: dict, key: str, *, min_val: float | None = None, max_val: float | None = None) -> float:
    v = d.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", f"{key} must be a number")
    if min_val is not None and v < min_val:
        raise ApiError("ERR_VALIDATION", f"{key} must be >= {min_val}")
    if max_val is not None and v > max_val:
        raise ApiError("ERR_VALIDATION", f"{key} must be <= {max_val}")
    return float(v)


def optional_num(
    d: dict, key: str, *, min_val: float | None = None, max_val: float | None = None
) -> float | None:
    if key not in d or d[key] is None:
        return None
    return require_num(d, key, min_val=min_val, max_val=max_val)


def optional_str(d: dict, key: str, *, max_len: int | None = None) -> str | None:
    if key not in d or d[key] is None:
        return None
    return require_str(d, key, max_len=max_len)
