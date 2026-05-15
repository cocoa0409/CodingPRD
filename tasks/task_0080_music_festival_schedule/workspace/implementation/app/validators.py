"""Lightweight per-field validators for the body-schema sanity rule
(priority-25 in §1.4).

Each helper raises `ApiError("ERR_INVALID_FIELD_VALUE", ...)` or
`ERR_INVALID_REQUEST_BODY` per the §2.4 prose.  Higher-priority checks
(auth, existence, state) run first in the route handler; these are the
last-ditch shape-and-type checks.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from .errors import ApiError


def require_field(body: dict, field: str) -> Any:
    """Return `body[field]` or raise ERR_INVALID_FIELD_VALUE."""
    if field not in body:
        raise ApiError("ERR_INVALID_FIELD_VALUE", f"missing required field {field!r}")
    val = body[field]
    if val is None:
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE", f"required field {field!r} cannot be null"
        )
    return val


def require_str(body: dict, field: str) -> str:
    v = require_field(body, field)
    if not isinstance(v, str) or v == "":
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE", f"field {field!r} must be a non-empty string"
        )
    return v


def optional_str(body: dict, field: str, default: Optional[str] = None) -> Optional[str]:
    v = body.get(field, default)
    if v is None:
        return default
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_FIELD_VALUE", f"field {field!r} must be a string")
    return v


def require_int(body: dict, field: str, *, positive: bool = False, non_negative: bool = False) -> int:
    v = require_field(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE", f"field {field!r} must be an integer"
        )
    if positive and v <= 0:
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE", f"field {field!r} must be a positive integer"
        )
    if non_negative and v < 0:
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE", f"field {field!r} must be a non-negative integer"
        )
    return int(v)


def optional_int(
    body: dict,
    field: str,
    *,
    default: Optional[int] = None,
    positive: bool = False,
    non_negative: bool = False,
) -> Optional[int]:
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE", f"field {field!r} must be an integer or null"
        )
    if positive and v <= 0:
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE", f"field {field!r} must be a positive integer"
        )
    if non_negative and v < 0:
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE", f"field {field!r} must be a non-negative integer"
        )
    return int(v)


def require_enum(body: dict, field: str, choices: Iterable[str]) -> str:
    v = require_str(body, field)
    choices_set = set(choices)
    if v not in choices_set:
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE",
            f"field {field!r} must be one of {sorted(choices_set)}",
        )
    return v


def require_bool(body: dict, field: str) -> bool:
    v = require_field(body, field)
    if not isinstance(v, bool):
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE", f"field {field!r} must be a boolean"
        )
    return bool(v)


def optional_bool(body: dict, field: str, *, default: bool = False) -> bool:
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE", f"field {field!r} must be a boolean"
        )
    return bool(v)


def require_list(body: dict, field: str, *, element_type: Optional[type] = None) -> list:
    v = require_field(body, field)
    if not isinstance(v, list):
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE", f"field {field!r} must be an array"
        )
    if element_type is not None:
        for item in v:
            if not isinstance(item, element_type):
                raise ApiError(
                    "ERR_INVALID_FIELD_VALUE",
                    f"every element of {field!r} must be of type {element_type.__name__}",
                )
    return v


def optional_list(
    body: dict, field: str, *, default: Optional[list] = None, element_type: Optional[type] = None
) -> list:
    if field not in body or body[field] is None:
        return list(default) if default is not None else []
    return require_list(body, field, element_type=element_type)


def require_dict(body: dict, field: str) -> dict:
    v = require_field(body, field)
    if not isinstance(v, dict):
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE", f"field {field!r} must be an object"
        )
    return v


def require_positive_unix_time(body: dict, field: str) -> int:
    """Per §2.4, integer Unix-seconds-UTC and strictly positive."""
    v = require_int(body, field)
    if v <= 0:
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE",
            f"field {field!r} must be a positive Unix-seconds integer",
        )
    return v


def require_window(body: dict, start_field: str, end_field: str) -> tuple[int, int]:
    """`end > start` on every windowed entity, per §2.4."""
    s = require_positive_unix_time(body, start_field)
    e = require_positive_unix_time(body, end_field)
    if e <= s:
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE",
            f"end_time {end_field!r} must be strictly greater than start_time {start_field!r}",
        )
    return s, e
