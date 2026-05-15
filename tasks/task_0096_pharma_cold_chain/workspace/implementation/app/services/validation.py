"""Common validation helpers — body parsing, OCC checks, type guards."""
from __future__ import annotations

from typing import Any, Iterable

from ..errors import ApiError


def require_keys(body: dict[str, Any], keys: Iterable[str]) -> None:
    missing = [k for k in keys if k not in body]
    if missing:
        raise ApiError("ERR_VALIDATION_FAILED", f"Missing required fields: {missing}")


def require_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ApiError("ERR_VALIDATION_FAILED", f"{name} must be a non-empty string")
    return value


def require_int(value: Any, name: str, *, allow_zero: bool = True, allow_neg: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_VALIDATION_FAILED", f"{name} must be an integer")
    if not allow_neg and value < 0:
        raise ApiError("ERR_VALIDATION_FAILED", f"{name} must be >= 0")
    if not allow_zero and value == 0:
        raise ApiError("ERR_VALIDATION_FAILED", f"{name} must be > 0")
    return value


def require_number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ApiError("ERR_VALIDATION_FAILED", f"{name} must be a number")
    if not isinstance(value, (int, float)):
        raise ApiError("ERR_VALIDATION_FAILED", f"{name} must be a number")
    return float(value)


def require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ApiError("ERR_VALIDATION_FAILED", f"{name} must be a boolean")
    return value


def require_enum(value: Any, name: str, allowed: Iterable[str]) -> str:
    s = require_str(value, name)
    allowed_set = set(allowed)
    if s not in allowed_set:
        raise ApiError("ERR_VALIDATION_FAILED", f"{name} must be one of {sorted(allowed_set)}")
    return s


def check_occ(entity: dict[str, Any], body: dict[str, Any]) -> None:
    """Optimistic concurrency check. PRD §2.5."""
    if "version" not in body or body["version"] is None:
        return
    v = body["version"]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION_FAILED", "version must be integer")
    if v != entity.get("version"):
        raise ApiError("ERR_VERSION_CONFLICT", "version mismatch")
