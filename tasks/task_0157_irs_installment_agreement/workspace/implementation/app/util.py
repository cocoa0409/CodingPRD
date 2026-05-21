"""Generic JSON body / query parameter validation helpers."""
from __future__ import annotations

from typing import Any, Iterable, Optional

from flask import request

from app.errors import ERR_VALIDATION, raise_error


def get_json_body() -> dict:
    """Return the JSON body of the request as a dict; raise ERR_VALIDATION otherwise."""
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        raise_error(ERR_VALIDATION, "Body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error(ERR_VALIDATION, "Body must be a JSON object.")
    return body


def require_fields(body: dict, fields: Iterable[str]):
    for f in fields:
        if f not in body or body[f] is None:
            raise_error(ERR_VALIDATION, f"Missing required field: {f}")


def require_str(body: dict, field: str, *, allow_empty: bool = False) -> str:
    v = body.get(field)
    if not isinstance(v, str):
        raise_error(ERR_VALIDATION, f"Field {field!r} must be a string.")
    if not allow_empty and not v.strip():
        raise_error(ERR_VALIDATION, f"Field {field!r} must not be empty.")
    return v


def require_int(body: dict, field: str, *, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_VALIDATION, f"Field {field!r} must be an integer.")
    if minimum is not None and v < minimum:
        raise_error(ERR_VALIDATION, f"Field {field!r} must be >= {minimum}.")
    if maximum is not None and v > maximum:
        raise_error(ERR_VALIDATION, f"Field {field!r} must be <= {maximum}.")
    return v


def require_enum(body: dict, field: str, allowed: Iterable[str]) -> str:
    v = require_str(body, field)
    if v not in set(allowed):
        raise_error(ERR_VALIDATION, f"Field {field!r} must be one of {sorted(set(allowed))}.")
    return v


def require_list(body: dict, field: str, *, min_len: int = 1) -> list:
    v = body.get(field)
    if not isinstance(v, list):
        raise_error(ERR_VALIDATION, f"Field {field!r} must be an array.")
    if len(v) < min_len:
        raise_error(ERR_VALIDATION, f"Field {field!r} must have at least {min_len} item(s).")
    return v


def optional_version(body: dict) -> Optional[int]:
    if "version" not in body or body["version"] is None:
        return None
    v = body["version"]
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_VALIDATION, "Field 'version' must be an integer when supplied.")
    return v


def get_pagination():
    """Read limit and offset from query string with defaults from the scaffold."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise_error(ERR_VALIDATION, "Query parameter 'limit' must be an integer.")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise_error(ERR_VALIDATION, "Query parameter 'offset' must be an integer.")
    if limit < 1 or limit > 100:
        raise_error(ERR_VALIDATION, "Query parameter 'limit' must be between 1 and 100.")
    if offset < 0:
        raise_error(ERR_VALIDATION, "Query parameter 'offset' must be >= 0.")
    return limit, offset


def paginate(items: list, limit: int, offset: int):
    return items[offset : offset + limit], len(items)
