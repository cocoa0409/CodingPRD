"""Shared request-validation and pagination helpers (PRD 2.3, 2.7 rung 4)."""

from flask import request

from errors import raise_err, ERR_INVALID_REQUEST
from timeutil import parse_instant


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None or raw_limit == "":
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if isinstance(limit, bool) or limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise_err(
                ERR_INVALID_REQUEST,
                f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}",
            )

    if raw_offset is None or raw_offset == "":
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if isinstance(offset, bool) or offset < 0:
            raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")

    return limit, offset


def paginate(items: list, limit: int, offset: int):
    """Return (page_items, total_count). Items must already be sorted."""
    total = len(items)
    return items[offset : offset + limit], total


# ---------------------------------------------------------------------------
# Body field validation (ladder rung 4)
# ---------------------------------------------------------------------------

def get_json_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_field(body: dict, name: str):
    if name not in body or body[name] is None:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    return body[name]


def require_string(body: dict, name: str) -> str:
    value = require_field(body, name)
    if not isinstance(value, str) or value == "":
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string")
    return value


def optional_string(body: dict, name: str, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, str):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a string")
    return value


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def require_number(body: dict, name: str):
    value = require_field(body, name)
    if not is_number(value):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a number")
    return value


def optional_number(body: dict, name: str, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not is_number(value):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a number")
    return value


def require_int(body: dict, name: str) -> int:
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    return value


def require_bool(body: dict, name: str) -> bool:
    value = require_field(body, name)
    if not isinstance(value, bool):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return value


def optional_bool(body: dict, name: str, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return value


def require_enum(body: dict, name: str, allowed) -> str:
    value = require_field(body, name)
    if not isinstance(value, str) or value not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(allowed)}")
    return value


def require_ts(body: dict, name: str) -> str:
    """Require an ISO 8601 timestamp; the raw string is stored verbatim."""
    value = require_field(body, name)
    if parse_instant(value) is None:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a valid ISO 8601 timestamp")
    return value


# ---------------------------------------------------------------------------
# List helpers
# ---------------------------------------------------------------------------

def sort_created_asc(items: list) -> list:
    """created_at ascending (PRD 2.3); ties broken by insertion order."""
    return sorted(items, key=lambda it: (parse_instant(it["created_at"]), it["_seq"]))


def apply_eq_filter(items: list, field: str):
    """Exact-match query filter; absent/empty parameter means no filtering."""
    value = request.args.get(field)
    if value is None or value == "":
        return items
    return [it for it in items if str(it.get(field)) == value]
