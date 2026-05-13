"""Common utilities: input parsing, pagination, OCC checks."""

from typing import Any, Iterable

from flask import request

from errors import (
    ERR_VALIDATION,
    ERR_VERSION_CONFLICT,
    raise_error,
)


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------


def get_json_body() -> dict:
    """Return the JSON request body as a dict. Empty body becomes {}."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise_error(ERR_VALIDATION, "malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error(ERR_VALIDATION, "JSON body must be an object")
    return body


def require_field(body: dict, name: str, type_=None) -> Any:
    if name not in body or body[name] is None:
        raise_error(ERR_VALIDATION, f"missing field '{name}'")
    val = body[name]
    if type_ is not None and not isinstance(val, type_):
        raise_error(ERR_VALIDATION, f"field '{name}' has wrong type")
    return val


def optional_field(body: dict, name: str, type_=None, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if type_ is not None and not isinstance(val, type_):
        raise_error(ERR_VALIDATION, f"field '{name}' has wrong type")
    return val


def require_non_empty_string(body: dict, name: str) -> str:
    val = require_field(body, name, str)
    if not val:
        raise_error(ERR_VALIDATION, f"field '{name}' must be non-empty")
    return val


def require_int(body: dict, name: str) -> int:
    val = require_field(body, name)
    # bool is subclass of int; reject
    if isinstance(val, bool) or not isinstance(val, int):
        raise_error(ERR_VALIDATION, f"field '{name}' must be integer")
    return val


def require_positive_int(body: dict, name: str) -> int:
    val = require_int(body, name)
    if val <= 0:
        raise_error(ERR_VALIDATION, f"field '{name}' must be > 0")
    return val


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def get_pagination(default_limit: int = 10, max_limit: int = 100):
    """Return (limit, offset). Raises ERR_VALIDATION on bad values."""
    args = request.args
    try:
        limit = int(args.get("limit", default_limit))
    except (ValueError, TypeError):
        raise_error(ERR_VALIDATION, "limit must be integer")
    try:
        offset = int(args.get("offset", 0))
    except (ValueError, TypeError):
        raise_error(ERR_VALIDATION, "offset must be integer")
    if limit < 1 or limit > max_limit:
        raise_error(ERR_VALIDATION, f"limit must be in [1,{max_limit}]")
    if offset < 0:
        raise_error(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def slice_page(items: list, limit: int, offset: int):
    """Return (page_items, total_count)."""
    total = len(items)
    return items[offset : offset + limit], total


# ---------------------------------------------------------------------------
# Optimistic concurrency
# ---------------------------------------------------------------------------


def check_occ(body: dict, entity: dict):
    """If body carries 'version', compare against entity['version']."""
    if "version" in body and body["version"] is not None:
        v = body["version"]
        if isinstance(v, bool) or not isinstance(v, int):
            raise_error(ERR_VALIDATION, "version must be integer")
        if v != entity.get("version"):
            raise_error(ERR_VERSION_CONFLICT, "OCC version mismatch")
