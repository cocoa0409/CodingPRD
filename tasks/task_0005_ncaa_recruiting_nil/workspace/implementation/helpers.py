"""Shared helpers: pagination, body parsing, type checks."""

from typing import Any, Optional

from flask import request

from errors import invalid_request


# Pagination defaults (per PRD §2.3, scaffold response_envelope.pagination_defaults)
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
    """Parse JSON body; tolerate empty body for POST actions with no input."""
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
    if name not in body:
        raise invalid_request(f"Required field {name!r} is missing.")
    val = body[name]
    if expected_type is not None and not isinstance(val, expected_type):
        # bool is a subclass of int in Python; tighten the check
        if expected_type is int and isinstance(val, bool):
            raise invalid_request(f"Field {name!r} must be of type int.")
        if expected_type is float:
            # allow int -> float since clients may send 0 instead of 0.0
            if not (isinstance(val, (int, float)) and not isinstance(val, bool)):
                raise invalid_request(f"Field {name!r} must be numeric.")
        else:
            raise invalid_request(
                f"Field {name!r} must be of type {expected_type.__name__}."
            )
    return val


def optional_field(body: dict, name: str, expected_type=None, default=None):
    if name not in body:
        return default
    val = body[name]
    if val is None:
        return default
    if expected_type is not None and not isinstance(val, expected_type):
        if expected_type is int and isinstance(val, bool):
            raise invalid_request(f"Field {name!r} must be of type int.")
        if expected_type is float:
            if not (isinstance(val, (int, float)) and not isinstance(val, bool)):
                raise invalid_request(f"Field {name!r} must be numeric.")
        else:
            raise invalid_request(
                f"Field {name!r} must be of type {expected_type.__name__}."
            )
    return val


def require_enum(value: Any, field: str, allowed: set):
    if value not in allowed:
        raise invalid_request(
            f"Field {field!r} must be one of {sorted(allowed)}."
        )
    return value


def sort_created_at_asc(items: list) -> list:
    return sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
