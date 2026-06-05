"""Shared helpers: pagination, body parsing, type/enum checks, sorting.

Pagination parameter names and defaults come from SCAFFOLD.yaml
response_envelope (limit/offset/total_count/has_more; default 10, min 1,
max 100, offset 0) and PRD §2.3.
"""

from typing import Any

from flask import request

from errors import invalid_request

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise invalid_request(
                f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}."
            )
    if raw_offset is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer.")
        if offset < 0:
            raise invalid_request("offset must be >= 0.")
    return limit, offset


def paginate(items: list, limit: int, offset: int):
    total = len(items)
    sliced = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return sliced, total, has_more


def get_body() -> dict:
    """Parse JSON body; tolerate an empty body for action POSTs with no input."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise invalid_request("Request body must be valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise invalid_request("Request body must be a JSON object.")
    return body


def require_field(body: dict, name: str, expected_type=None):
    if name not in body or body[name] is None:
        raise invalid_request(f"Required field {name!r} is missing.")
    val = body[name]
    _check_type(val, name, expected_type)
    return val


def optional_field(body: dict, name: str, expected_type=None, default=None):
    if name not in body:
        return default
    val = body[name]
    if val is None:
        return default
    _check_type(val, name, expected_type)
    return val


def _check_type(val: Any, name: str, expected_type):
    if expected_type is None:
        return
    # bool is a subclass of int in Python; reject bool where int is required.
    if expected_type is int:
        if isinstance(val, bool) or not isinstance(val, int):
            raise invalid_request(f"Field {name!r} must be of type int.")
        return
    if expected_type is bool:
        if not isinstance(val, bool):
            raise invalid_request(f"Field {name!r} must be a boolean.")
        return
    if not isinstance(val, expected_type):
        raise invalid_request(
            f"Field {name!r} must be of type {expected_type.__name__}."
        )


def require_enum(value: Any, field: str, allowed: set):
    if value not in allowed:
        raise invalid_request(
            f"Field {field!r} must be one of {sorted(allowed)}."
        )
    return value


def sort_created_at_asc(items: list) -> list:
    """Sort by creation timestamp ascending (PRD §2.3). Ties broken by the
    monotonic creation sequence so same-millisecond rows keep insertion order."""
    return sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
