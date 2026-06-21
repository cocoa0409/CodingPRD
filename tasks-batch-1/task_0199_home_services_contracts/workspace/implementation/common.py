"""Shared helpers: body parsing, type/enum validation, datetime parsing,
pagination, serialization."""
from datetime import datetime, timezone

from flask import request

from errors import err


# ---------------------------------------------------------------------------
# Request body
# ---------------------------------------------------------------------------
def get_body():
    """Return the parsed JSON body as a dict, or {} when no body was sent.

    A present-but-malformed (non-JSON) body -> ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    return body[field]


def req_int(body, field, minimum=None):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (field, minimum))
    return v


def opt_int(body, field, default=None, minimum=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (field, minimum))
    return v


def req_str(body, field, non_empty=False):
    v = require(body, field)
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string" % field)
    if non_empty and v == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be non-empty" % field)
    return v


def opt_str(body, field, default=""):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string" % field)
    return v


def req_enum(body, field, allowed):
    v = require(body, field)
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, sorted(allowed)))
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, sorted(allowed)))
    return v


def req_bool(body, field):
    v = require(body, field)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)
    return v


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)
    return v


def req_number(body, field, lo=None, hi=None):
    """A JSON number (int or float). Used for parts_discount_pct (0..1)."""
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % field)
    if lo is not None and v < lo:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (field, lo))
    if hi is not None and v > hi:
        raise err("ERR_INVALID_REQUEST", "Field %s must be <= %s" % (field, hi))
    return v


# ---------------------------------------------------------------------------
# Datetime parsing (ISO 8601 UTC)
# ---------------------------------------------------------------------------
def parse_dt(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return None
    raw = body[field]
    return parse_iso(raw)


def parse_iso(raw):
    if not isinstance(raw, str):
        raise err("ERR_INVALID_REQUEST", "Datetime must be an ISO 8601 string")
    s = raw.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Invalid ISO 8601 datetime: %s" % raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------
def pagination():
    limit = _qp_int("limit", 10)
    offset = _qp_int("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _qp_int(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "Query parameter %s must be an integer" % name)


def paginate(rows, limit, offset):
    """rows: list already sorted by created_at ASC. Returns (page, total)."""
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, total


def sort_by_created(rows):
    """List default sort: created_at ASC (PRD §2.3), tie-break by insertion seq."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
