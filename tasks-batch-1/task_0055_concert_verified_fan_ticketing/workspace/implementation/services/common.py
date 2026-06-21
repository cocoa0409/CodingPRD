"""Shared lookup / validation helpers."""
from __future__ import annotations

from typing import Any, Dict, Optional

import db
from errors import (
    APIError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
)


def get_or_404(store: Dict[str, Dict], rid: Optional[str], label: str) -> dict:
    if rid is None or rid not in store:
        raise APIError(ERR_NOT_FOUND, 404, f"{label} not found")
    return store[rid]


def require_fields(body: dict, fields) -> None:
    for f in fields:
        if f not in body or body[f] is None:
            raise APIError(ERR_INVALID_REQUEST, 400, f"Missing required field: {f}")


def require_str(body: dict, field: str, allow_empty: bool = False) -> str:
    if field not in body or body[field] is None:
        raise APIError(ERR_INVALID_REQUEST, 400, f"Missing required field: {field}")
    val = body[field]
    if not isinstance(val, str):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field} must be a string")
    if not allow_empty and val == "":
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field} must be non-empty")
    return val


def require_int(body: dict, field: str) -> int:
    if field not in body or body[field] is None:
        raise APIError(ERR_INVALID_REQUEST, 400, f"Missing required field: {field}")
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field} must be an integer")
    return val


def optional_int(body: dict, field: str, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field} must be an integer")
    return val


def sorted_by_creation(items):
    """Stable ascending order by (created_at, _seq)."""
    return sorted(items, key=lambda o: (o.get("created_at", ""), o.get("_seq", 0)))
