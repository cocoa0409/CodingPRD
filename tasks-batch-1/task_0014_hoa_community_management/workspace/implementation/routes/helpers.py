"""Shared helpers for route handlers."""
from __future__ import annotations

from flask import request

from errors import (
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    raise_err,
)


def get_json_body() -> dict:
    """Return JSON body or empty dict; reject malformed JSON."""
    if request.method == "GET" or not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise_err(ERR_INVALID_REQUEST, "Request body must be valid JSON")
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_field(body: dict, name: str, expected_type=None):
    if name not in body:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    value = body[name]
    if expected_type is not None and not isinstance(value, expected_type):
        # bool is subclass of int; reject bool when expecting int
        if expected_type is int and isinstance(value, bool):
            raise_err(ERR_INVALID_REQUEST,
                      f"Field {name} must be of type {expected_type.__name__}")
        if not isinstance(value, expected_type):
            raise_err(ERR_INVALID_REQUEST,
                      f"Field {name} must be of type {expected_type.__name__}")
    return value


def require_int(body: dict, name: str, *, min_value=None, max_value=None):
    if name not in body:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    if min_value is not None and value < min_value:
        raise_err(ERR_INVALID_REQUEST,
                  f"Field {name} must be >= {min_value}")
    if max_value is not None and value > max_value:
        raise_err(ERR_INVALID_REQUEST,
                  f"Field {name} must be <= {max_value}")
    return value


def optional_int(body: dict, name: str, default=None, *, min_value=None,
                 max_value=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    if min_value is not None and value < min_value:
        raise_err(ERR_INVALID_REQUEST,
                  f"Field {name} must be >= {min_value}")
    if max_value is not None and value > max_value:
        raise_err(ERR_INVALID_REQUEST,
                  f"Field {name} must be <= {max_value}")
    return value


def require_str(body: dict, name: str):
    if name not in body:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    value = body[name]
    if not isinstance(value, str) or value == "":
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string")
    return value


def require_enum(body: dict, name: str, allowed: set[str]):
    value = require_str(body, name)
    if value not in allowed:
        raise_err(ERR_INVALID_REQUEST,
                  f"Field {name} must be one of {sorted(allowed)}")
    return value


def parse_pagination():
    """Return (limit, offset) per PRD §2.3 (defaults: 10, 0; limit 1..100)."""
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    try:
        limit = int(limit_s) if limit_s is not None else 10
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(offset_s) if offset_s is not None else 0
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_err(ERR_INVALID_REQUEST, "limit must be in [1, 100]")
    if offset < 0:
        raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def fetch_or_404(store: dict, key: str, label: str) -> dict:
    item = store.get(key)
    if item is None:
        raise_err(ERR_NOT_FOUND, f"{label} not found: {key}")
    return item


def paginate(rows: list, limit: int, offset: int) -> tuple[list, int]:
    """Sort by created_at ascending (per PRD §2.3), apply limit/offset."""
    sortable = sorted(
        rows,
        key=lambda r: r.get("created_at") or r.get("applied_at") or r.get("cast_at") or "",
    )
    total = len(sortable)
    page = sortable[offset: offset + limit]
    return page, total
