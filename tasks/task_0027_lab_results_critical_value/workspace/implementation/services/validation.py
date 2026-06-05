"""Shared validation helpers (used by route handlers).

Enforces PRD §2.10 priority order:
  ERR_UNAUTHENTICATED (handled by middleware)
  ERR_UNAUTHORIZED   (handled by middleware)
  ERR_NOT_FOUND       (existence checks)
  ERR_INVALID_STATE   (state-machine guard)
  + ERR_INVALID_REQUEST for structural request problems (HTTP 400).
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Dict, Optional

from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
)


# ---------- input-shape helpers ---------------------------------------------

def require_fields(body: dict, fields: Iterable[str]) -> None:
    missing = [f for f in fields if body.get(f) is None]
    if missing:
        raise APIError(
            ERR_INVALID_REQUEST, 400,
            f"Missing required field(s): {', '.join(missing)}",
        )


def require_string(value: Any, name: str, min_len: int = 1, max_len: int = 10_000) -> str:
    if not isinstance(value, str):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be a string")
    if len(value) < min_len or len(value) > max_len:
        raise APIError(ERR_INVALID_REQUEST, 400,
                       f"{name} length must be in [{min_len}, {max_len}]")
    return value


def require_int(value: Any, name: str, min_v: Optional[int] = None,
                max_v: Optional[int] = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be an integer")
    if min_v is not None and value < min_v:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be >= {min_v}")
    if max_v is not None and value > max_v:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be <= {max_v}")
    return value


def require_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be a number")
    return float(value)


def require_enum(value: Any, choices: Iterable[str], name: str) -> str:
    if value not in choices:
        raise APIError(
            ERR_INVALID_REQUEST, 400,
            f"{name} must be one of: {', '.join(sorted(choices))}",
        )
    return value


def require_list(value: Any, name: str) -> list:
    if not isinstance(value, list):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be an array")
    return value


# ---------- existence ------------------------------------------------------

def lookup_or_404(store: Dict[str, Dict[str, Any]], _id: str, entity: str) -> Dict[str, Any]:
    if not isinstance(_id, str) or _id not in store:
        raise APIError(ERR_NOT_FOUND, 404, f"{entity} '{_id}' not found")
    return store[_id]


# ---------- regex patterns -------------------------------------------------

MRN_PATTERN = re.compile(r"^MRN-[A-Z0-9]{6}$")
NPI_PATTERN = re.compile(r"^[0-9]{10}$")
PHONE_PATTERN = re.compile(r"^\+[1-9][0-9]{1,14}$")


def require_pattern(value: str, pattern: re.Pattern, name: str) -> str:
    if not isinstance(value, str) or not pattern.match(value):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} has invalid format")
    return value
