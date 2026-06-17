"""Shared validation, pagination, and field-extraction helpers."""
from __future__ import annotations

from flask import request

from errors import APIError, ERR_INVALID_REQUEST

# Pagination defaults (PRD §2.3 / scaffold response_envelope.pagination_defaults)
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _bad(msg: str) -> APIError:
    return APIError(ERR_INVALID_REQUEST, 422, msg)


def require_present(body: dict, *names: str) -> None:
    for name in names:
        if name not in body or body[name] is None:
            raise _bad(f"Missing required field: {name}")


def as_string(body: dict, name: str, required: bool = True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise _bad(f"Missing required field: {name}")
        return default
    val = body[name]
    if not isinstance(val, str):
        raise _bad(f"Field {name} must be a string")
    return val


def as_nonempty_string(body: dict, name: str, required: bool = True, default=None):
    val = as_string(body, name, required=required, default=default)
    if val is not None and isinstance(val, str) and val == "" and required:
        raise _bad(f"Field {name} must be a non-empty string")
    return val


def as_int(body: dict, name: str, required: bool = True, default=None,
           min_value=None, max_value=None):
    if name not in body or body[name] is None:
        if required:
            raise _bad(f"Missing required field: {name}")
        return default
    val = body[name]
    # bool is a subclass of int — reject it as a numeric value
    if isinstance(val, bool) or not isinstance(val, int):
        raise _bad(f"Field {name} must be an integer")
    if min_value is not None and val < min_value:
        raise _bad(f"Field {name} must be >= {min_value}")
    if max_value is not None and val > max_value:
        raise _bad(f"Field {name} must be <= {max_value}")
    return val


def as_number(body: dict, name: str, required: bool = True, default=None,
              min_value=None, max_value=None):
    if name not in body or body[name] is None:
        if required:
            raise _bad(f"Missing required field: {name}")
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise _bad(f"Field {name} must be a number")
    if min_value is not None and val < min_value:
        raise _bad(f"Field {name} must be >= {min_value}")
    if max_value is not None and val > max_value:
        raise _bad(f"Field {name} must be <= {max_value}")
    return val


def as_bool(body: dict, name: str, required: bool = True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise _bad(f"Missing required field: {name}")
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise _bad(f"Field {name} must be a boolean")
    return val


def as_enum(body: dict, name: str, choices, required: bool = True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise _bad(f"Missing required field: {name}")
        return default
    val = body[name]
    if not isinstance(val, str) or val not in choices:
        raise _bad(f"Field {name} must be one of {sorted(choices)}")
    return val


def parse_pagination():
    """Read & validate limit/offset query params (PRD §2.3)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = PAGE_LIMIT_DEFAULT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise _bad("limit must be an integer")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise _bad(f"limit must be between {PAGE_LIMIT_MIN} and {PAGE_LIMIT_MAX}")

    if offset_raw is None:
        offset = PAGE_OFFSET_DEFAULT
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise _bad("offset must be an integer")
        if offset < 0:
            raise _bad("offset must be >= 0")

    return limit, offset


def paginate(collection_values, limit, offset, filters=None):
    """Apply filters, sort by created_at ascending (seq tiebreak), and page.

    filters: list of predicate callables.
    Returns (page_items, total_count).
    """
    items = list(collection_values)
    if filters:
        for pred in filters:
            items = [it for it in items if pred(it)]
    items.sort(key=lambda it: (it["created_at"], it.get("_seq", 0)))
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
