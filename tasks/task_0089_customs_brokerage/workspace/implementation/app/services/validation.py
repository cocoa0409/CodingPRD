"""Shared input validation helpers."""
from __future__ import annotations

import re
from typing import Any, Optional

from ..constants import CURRENCIES
from ..errors import ApiError


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def ensure_string(value: Any, field: str, min_len: int = 1, max_len: int = 200) -> str:
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_INPUT", f"{field} must be a string.")
    if len(value) < min_len or len(value) > max_len:
        raise ApiError(
            "ERR_INVALID_INPUT",
            f"{field} length must be in [{min_len}, {max_len}].",
        )
    return value


def ensure_enum(value: Any, field: str, allowed: set[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(
            "ERR_INVALID_INPUT",
            f"{field} must be one of {sorted(allowed)}; got {value!r}.",
        )
    return value


def ensure_currency(value: Any, field: str) -> str:
    return ensure_enum(value, field, CURRENCIES)


def ensure_email(value: Any, field: str) -> str:
    s = ensure_string(value, field, 1, 200)
    if not EMAIL_RE.match(s):
        raise ApiError("ERR_INVALID_INPUT", f"{field} must be a valid email.")
    return s


def ensure_country(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 2 or not value.isalpha() or value != value.upper():
        raise ApiError(
            "ERR_INVALID_INPUT",
            f"{field} must be a 2-letter uppercase ISO alpha-2 country code.",
        )
    return value


def ensure_non_negative_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ApiError("ERR_INVALID_INPUT", f"{field} must be a number.")
    if not isinstance(value, (int, float)):
        raise ApiError("ERR_INVALID_INPUT", f"{field} must be a number.")
    if value < 0:
        raise ApiError("ERR_INVALID_INPUT", f"{field} must be >= 0.")
    return float(value)


def ensure_int_in_range(value: Any, field: str, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_INPUT", f"{field} must be an integer.")
    if value < lo or value > hi:
        raise ApiError("ERR_INVALID_INPUT", f"{field} must be in [{lo}, {hi}].")
    return value


def ensure_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_INPUT", f"{field} must be a boolean.")
    return value


def ensure_hs_code(value: Any, field: str = "hs_code") -> str:
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_INPUT", f"{field} must be a numeric string.")
    if not value.isdigit():
        raise ApiError("ERR_INVALID_INPUT", f"{field} must contain only digits.")
    if len(value) not in (6, 8, 10):
        raise ApiError("ERR_INVALID_INPUT", f"{field} length must be 6, 8, or 10.")
    return value


def coerce_optional_version(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_INPUT", "version must be an integer.")
    return value


def occ_check(entity: dict[str, Any], request_version: Optional[int]) -> None:
    """Optimistic concurrency: error on mismatch; skip when version absent."""
    if request_version is None:
        return
    current = int(entity.get("version", 0))
    if request_version != current:
        raise ApiError(
            "ERR_VERSION_CONFLICT",
            f"Version conflict: expected {current}, got {request_version}.",
        )
