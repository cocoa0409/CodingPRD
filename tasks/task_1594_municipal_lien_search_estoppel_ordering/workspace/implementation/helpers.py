"""Generic request-body validation, date parsing, and pagination helpers."""
import re
from datetime import datetime, timezone

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_MISSING = object()


def body():
    """Return the JSON request body as a dict; {} when absent."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def _bad(msg):
    raise ApiError(ERR_INVALID_REQUEST, 400, msg)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(b, key):
    v = b.get(key, _MISSING)
    if v is _MISSING or not isinstance(v, str) or v == "":
        _bad(f"{key} is required and must be a non-empty string")
    return v


def opt_str(b, key, default=None):
    v = b.get(key, _MISSING)
    if v is _MISSING or v is None:
        return default
    if not isinstance(v, str) or v == "":
        _bad(f"{key} must be a non-empty string")
    return v


def req_int(b, key, minimum=None):
    v = b.get(key, _MISSING)
    if v is _MISSING or not is_int(v):
        _bad(f"{key} is required and must be an integer")
    if minimum is not None and v < minimum:
        _bad(f"{key} must be >= {minimum}")
    return v


def opt_int(b, key, default=None, minimum=None):
    v = b.get(key, _MISSING)
    if v is _MISSING or v is None:
        return default
    if not is_int(v):
        _bad(f"{key} must be an integer")
    if minimum is not None and v < minimum:
        _bad(f"{key} must be >= {minimum}")
    return v


def req_bool(b, key):
    v = b.get(key, _MISSING)
    if v is _MISSING or not isinstance(v, bool):
        _bad(f"{key} is required and must be a boolean")
    return v


def opt_bool(b, key, default=False):
    v = b.get(key, _MISSING)
    if v is _MISSING or v is None:
        return default
    if not isinstance(v, bool):
        _bad(f"{key} must be a boolean")
    return v


def parse_date(s, field):
    if not isinstance(s, str) or not DATE_RE.match(s):
        _bad(f"{field} must be an ISO date string (YYYY-MM-DD)")
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        _bad(f"{field} is not a valid calendar date")


def req_date(b, key):
    v = b.get(key, _MISSING)
    if v is _MISSING or v is None:
        _bad(f"{key} is required")
    return parse_date(v, key)


def opt_date(b, key, default=None):
    v = b.get(key, _MISSING)
    if v is _MISSING or v is None:
        return default
    return parse_date(v, key)


def parse_instant(s):
    """Parse an ISO-8601 instant (with Z or offset) into an aware UTC datetime."""
    if not isinstance(s, str) or not s.strip():
        _bad("to_iso8601 must be an ISO-8601 timestamp string")
    t = s.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        _bad("to_iso8601 is not a valid ISO-8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def pagination_params():
    """limit/offset per PRD 2.3: default 10/0, clamped to [1,100] / [0,inf)."""
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def sort_items(items):
    """created_at ASC; identical logical-clock timestamps broken by insertion order."""
    return sorted(items, key=lambda x: (x["created_at"], x["_seq"]))


def paginate(items):
    """Slice a pre-filtered item list; return (page, pagination-meta-dict)."""
    ordered = sort_items(items)
    limit, offset = pagination_params()
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta
