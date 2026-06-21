"""Shared helpers: timestamps, common fields, pagination, payload validation,
rounding, datetime parsing.
"""
import datetime
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors
from db import store


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------
def iso_now():
    """ISO 8601 UTC timestamp with three fractional digits (real wall clock).

    Used for created_at / updated_at on resources. These are distinct from the
    logical clock (store.now()), which only governs scheduled-order release.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}".format(now.microsecond // 1000) + "Z"


def parse_iso8601(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Returns None on failure.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


# ---------------------------------------------------------------------------
# Rounding (PRD §2.8: round half up)
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a numeric value to the nearest integer, half rounds up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Common system-managed fields (PRD §2.4)
# ---------------------------------------------------------------------------
def init_common(versioned=True):
    """Return a fresh common-field dict for a new resource.

    versioned=True -> id / created_at / updated_at / version (the full set).
    versioned=False -> id / created_at only (TipAdjustment log entity).
    """
    ts = iso_now()
    base = {
        "id": store.new_id(),
        "created_at": ts,
        "_seq": store.next_seq(),
    }
    if versioned:
        base["updated_at"] = ts
        base["version"] = 1
    return base


def touch(entity):
    """Refresh updated_at and increment version on a mutation (PRD §2.4, §2.5)."""
    entity["updated_at"] = iso_now()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------
def get_json_body():
    """Return the parsed JSON body, or {} when absent. Malformed JSON -> 400."""
    if request.data is None or len(request.data) == 0:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.err(errors.ERR_INVALID_PAYLOAD, "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.err(errors.ERR_INVALID_PAYLOAD, "Request body must be a JSON object")
    return body


def require_field(body, name):
    if name not in body or body[name] is None:
        raise errors.err(errors.ERR_INVALID_PAYLOAD, "Missing required field: " + name)
    return body[name]


def require_int(body, name, minimum=None, maximum=None):
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.err(errors.ERR_INVALID_PAYLOAD, "Field must be an integer: " + name)
    _check_range(name, value, minimum, maximum)
    return value


def optional_int(body, name, default=None, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.err(errors.ERR_INVALID_PAYLOAD, "Field must be an integer: " + name)
    _check_range(name, value, minimum, maximum)
    return value


def _check_range(name, value, minimum, maximum):
    if minimum is not None and value < minimum:
        raise errors.err(errors.ERR_INVALID_PAYLOAD, "Field below minimum: " + name)
    if maximum is not None and value > maximum:
        raise errors.err(errors.ERR_INVALID_PAYLOAD, "Field above maximum: " + name)


def require_str(body, name):
    value = require_field(body, name)
    if not isinstance(value, str):
        raise errors.err(errors.ERR_INVALID_PAYLOAD, "Field must be a string: " + name)
    return value


def optional_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, str):
        raise errors.err(errors.ERR_INVALID_PAYLOAD, "Field must be a string: " + name)
    return value


def optional_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise errors.err(errors.ERR_INVALID_PAYLOAD, "Field must be a boolean: " + name)
    return value


def require_number(body, name, minimum=None):
    """A numeric field that may be int or float (e.g. surge multipliers)."""
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise errors.err(errors.ERR_INVALID_PAYLOAD, "Field must be a number: " + name)
    if minimum is not None and value < minimum:
        raise errors.err(errors.ERR_INVALID_PAYLOAD, "Field below minimum: " + name)
    return value


def optional_number(body, name, default=None, minimum=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise errors.err(errors.ERR_INVALID_PAYLOAD, "Field must be a number: " + name)
    if minimum is not None and value < minimum:
        raise errors.err(errors.ERR_INVALID_PAYLOAD, "Field below minimum: " + name)
    return value


def optional_enum(body, name, allowed, default=None):
    """An optional enum field. Undeclared value -> ERR_INVALID_ENUM (422)."""
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if value not in allowed:
        raise errors.err(errors.ERR_INVALID_ENUM, "Invalid value for enum field: " + name)
    return value


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------
def parse_pagination():
    limit = _parse_query_int("limit", default=10)
    offset = _parse_query_int("offset", default=0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _parse_query_int(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def paginate(items, limit, offset):
    """Slice a sorted list and return (page, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def sorted_by_creation(items):
    """Default list ordering: ascending by creation (PRD §2.3)."""
    return sorted(items, key=lambda e: e["_seq"])
