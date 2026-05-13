from __future__ import annotations

"""Field-shape validation helpers and pagination parsers.

Validators raise APIError with the appropriate error_id.
"""

from typing import Any

from flask import request

from clock import parse_iso
from errors import (
    ERR_FIELD_VALIDATION,
    raise_error,
)


def get_json_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error(ERR_FIELD_VALIDATION, "Request body must be a JSON object")
    return body


def require_string(body: dict, key: str, *, min_len: int = 1, max_len: int = 10_000) -> str:
    v = body.get(key)
    if not isinstance(v, str):
        raise_error(ERR_FIELD_VALIDATION, f"'{key}' must be a string")
    if len(v) < min_len or len(v) > max_len:
        raise_error(ERR_FIELD_VALIDATION, f"'{key}' length must be in [{min_len},{max_len}]")
    if min_len >= 1 and not v.strip():
        raise_error(ERR_FIELD_VALIDATION, f"'{key}' must be non-empty")
    return v


def optional_string(body: dict, key: str, *, max_len: int = 10_000) -> str | None:
    if key not in body or body[key] is None:
        return None
    v = body[key]
    if not isinstance(v, str):
        raise_error(ERR_FIELD_VALIDATION, f"'{key}' must be a string")
    if len(v) > max_len:
        raise_error(ERR_FIELD_VALIDATION, f"'{key}' length exceeds {max_len}")
    return v


def require_enum(body: dict, key: str, allowed: set[str], *, default: str | None = None) -> str:
    v = body.get(key, default)
    if v is None:
        raise_error(ERR_FIELD_VALIDATION, f"'{key}' is required")
    if v not in allowed:
        raise_error(ERR_FIELD_VALIDATION, f"'{key}' must be one of {sorted(allowed)}")
    return v


def optional_enum(body: dict, key: str, allowed: set[str]) -> str | None:
    if key not in body or body[key] is None:
        return None
    v = body[key]
    if v not in allowed:
        raise_error(ERR_FIELD_VALIDATION, f"'{key}' must be one of {sorted(allowed)}")
    return v


def require_int(body: dict, key: str, *, min_value: int | None = None) -> int:
    v = body.get(key)
    if not isinstance(v, int) or isinstance(v, bool):
        raise_error(ERR_FIELD_VALIDATION, f"'{key}' must be an integer")
    if min_value is not None and v < min_value:
        raise_error(ERR_FIELD_VALIDATION, f"'{key}' must be >= {min_value}")
    return v


def require_datetime(body: dict, key: str) -> str:
    v = body.get(key)
    if not isinstance(v, str):
        raise_error(ERR_FIELD_VALIDATION, f"'{key}' must be an ISO 8601 UTC datetime string")
    try:
        parse_iso(v)
    except ValueError:
        raise_error(ERR_FIELD_VALIDATION, f"'{key}' is not a valid ISO 8601 UTC datetime")
    return v


def optional_array_of_strings(body: dict, key: str) -> list[str]:
    if key not in body or body[key] is None:
        return []
    v = body[key]
    if not isinstance(v, list):
        raise_error(ERR_FIELD_VALIDATION, f"'{key}' must be an array of strings")
    out = []
    for item in v:
        if not isinstance(item, str):
            raise_error(ERR_FIELD_VALIDATION, f"'{key}' must contain only strings")
        out.append(item)
    return out


def get_pagination() -> tuple[int, int]:
    limit_raw = request.args.get("limit", "10")
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        raise_error(ERR_FIELD_VALIDATION, "'limit' must be an integer")
    try:
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise_error(ERR_FIELD_VALIDATION, "'offset' must be an integer")
    if limit < 1 or limit > 100:
        raise_error(ERR_FIELD_VALIDATION, "'limit' must be in [1, 100]")
    if offset < 0:
        raise_error(ERR_FIELD_VALIDATION, "'offset' must be >= 0")
    return limit, offset


def sort_default(rows: list[dict]) -> list[dict]:
    """Sort by created_at asc, id asc."""
    return sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("id", "")))


def check_version(body: dict, entity: dict) -> None:
    """If body carries 'version', it must match entity.version."""
    if "version" not in body or body["version"] is None:
        return
    v = body["version"]
    if not isinstance(v, int) or isinstance(v, bool):
        raise_error(ERR_FIELD_VALIDATION, "'version' must be an integer")
    from errors import ERR_VERSION_CONFLICT
    if v != entity.get("version"):
        raise_error(ERR_VERSION_CONFLICT, "version does not match current entity version")
