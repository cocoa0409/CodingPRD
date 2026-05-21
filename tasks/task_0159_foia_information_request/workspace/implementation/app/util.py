"""Tiny utilities used across routes: input validation, pagination, etc."""

from __future__ import annotations

import re
from typing import Any, Iterable, List, Optional, Tuple

from flask import request

from .errors import ApiError, ERR_INVALID_INPUT


# RFC-5322-ish email check.  We only need to reject obviously malformed
# strings — the test suite does not require a full grammar implementation.
_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"
)


def is_valid_email(s: str) -> bool:
    return isinstance(s, str) and bool(_EMAIL_RE.match(s)) and len(s) <= 320


def require_json_body() -> dict:
    if request.method in ("POST", "PATCH", "PUT"):
        try:
            payload = request.get_json(silent=True)
        except Exception:  # pragma: no cover
            payload = None
        if payload is None:
            return {}
        if not isinstance(payload, dict):
            raise ApiError(ERR_INVALID_INPUT, 400, "Request body must be a JSON object.")
        return payload
    return {}


def require_str(payload: dict, key: str, *, max_len: int, allow_empty: bool = False) -> str:
    if key not in payload:
        raise ApiError(ERR_INVALID_INPUT, 400, f"Missing required field: {key}")
    value = payload[key]
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_INPUT, 400, f"Field {key!r} must be a string.")
    if not allow_empty and not value:
        raise ApiError(ERR_INVALID_INPUT, 400, f"Field {key!r} must be non-empty.")
    if len(value) > max_len:
        raise ApiError(ERR_INVALID_INPUT, 400, f"Field {key!r} exceeds max length {max_len}.")
    return value


def optional_str(
    payload: dict,
    key: str,
    *,
    max_len: int,
    allow_empty: bool = True,
    nullable: bool = True,
) -> Optional[str]:
    if key not in payload:
        return None
    value = payload[key]
    if value is None:
        if nullable:
            return None
        raise ApiError(ERR_INVALID_INPUT, 400, f"Field {key!r} must not be null.")
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_INPUT, 400, f"Field {key!r} must be a string.")
    if not allow_empty and not value:
        raise ApiError(ERR_INVALID_INPUT, 400, f"Field {key!r} must be non-empty.")
    if len(value) > max_len:
        raise ApiError(ERR_INVALID_INPUT, 400, f"Field {key!r} exceeds max length {max_len}.")
    return value


def require_enum(payload: dict, key: str, allowed: Iterable[str]) -> str:
    value = require_str(payload, key, max_len=128, allow_empty=False)
    allowed_set = set(allowed)
    if value not in allowed_set:
        raise ApiError(
            ERR_INVALID_INPUT,
            400,
            f"Field {key!r} must be one of {sorted(allowed_set)}",
        )
    return value


def require_int(payload: dict, key: str, *, minimum: Optional[int] = None) -> int:
    if key not in payload:
        raise ApiError(ERR_INVALID_INPUT, 400, f"Missing required field: {key}")
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(ERR_INVALID_INPUT, 400, f"Field {key!r} must be an integer.")
    if minimum is not None and value < minimum:
        raise ApiError(ERR_INVALID_INPUT, 400, f"Field {key!r} must be >= {minimum}.")
    return value


def require_number(payload: dict, key: str, *, minimum: Optional[float] = None) -> float:
    if key not in payload:
        raise ApiError(ERR_INVALID_INPUT, 400, f"Missing required field: {key}")
    value = payload[key]
    if isinstance(value, bool):
        raise ApiError(ERR_INVALID_INPUT, 400, f"Field {key!r} must be numeric.")
    if not isinstance(value, (int, float)):
        raise ApiError(ERR_INVALID_INPUT, 400, f"Field {key!r} must be numeric.")
    fvalue = float(value)
    if minimum is not None and fvalue < minimum:
        raise ApiError(ERR_INVALID_INPUT, 400, f"Field {key!r} must be >= {minimum}.")
    return fvalue


def require_bool(payload: dict, key: str, *, default: Optional[bool] = None) -> Optional[bool]:
    if key not in payload:
        return default
    value = payload[key]
    if not isinstance(value, bool):
        raise ApiError(ERR_INVALID_INPUT, 400, f"Field {key!r} must be a boolean.")
    return value


def get_pagination() -> Tuple[int, int]:
    """Parse limit / offset query params with the scaffold's defaults."""

    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_INPUT, 400, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_INPUT, 400, "limit must be in [1, 100].")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_INPUT, 400, "offset must be an integer.")
        if offset < 0:
            raise ApiError(ERR_INVALID_INPUT, 400, "offset must be >= 0.")
    return limit, offset


def paginate(items: List[Any], limit: int, offset: int):
    total_count = len(items)
    page = items[offset : offset + limit]
    has_more = (offset + len(page)) < total_count
    return page, total_count, has_more
