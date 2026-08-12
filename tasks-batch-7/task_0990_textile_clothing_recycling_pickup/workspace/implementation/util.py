"""Parsing, validation and pagination helpers."""
import re
from datetime import datetime, timezone

from flask import request

from errors import fail

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_dt(value):
    """Parse an ISO 8601 timestamp to an aware UTC datetime; None if invalid."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and v == v and v not in (float("inf"), float("-inf")))


def is_valid_date_str(v):
    if not isinstance(v, str) or not _DATE_RE.match(v):
        return False
    try:
        datetime.strptime(v, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def get_body():
    """Request JSON body as a dict. Empty body -> {}. Non-object JSON -> 400."""
    data = request.get_data(cache=True)
    if data is None or len(data) == 0:
        return {}
    import json
    try:
        body = json.loads(data)
    except (ValueError, TypeError):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def check_fields(body, spec):
    """spec: {name: (kind, required)}. Enforces declared-fields-only and types.

    kinds: str, int, num, bool, dt, date, list, obj, any, or ("enum", (values...)).
    Range/semantic checks live in the route handlers at their priority level.
    """
    for key in body:
        if key not in spec:
            fail("ERR_INVALID_REQUEST", "Undeclared field: %s" % key)
    for name, rule in spec.items():
        kind, required = rule
        if name not in body:
            if required:
                fail("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
            continue
        v = body[name]
        if kind == "str":
            if not isinstance(v, str):
                fail("ERR_INVALID_REQUEST", "Field %s must be a string" % name)
        elif kind == "int":
            if not is_int(v):
                fail("ERR_INVALID_REQUEST", "Field %s must be an integer" % name)
        elif kind == "num":
            if not is_num(v):
                fail("ERR_INVALID_REQUEST", "Field %s must be a number" % name)
        elif kind == "bool":
            if not isinstance(v, bool):
                fail("ERR_INVALID_REQUEST", "Field %s must be a boolean" % name)
        elif kind == "dt":
            if parse_dt(v) is None:
                fail("ERR_INVALID_REQUEST", "Field %s must be an ISO8601 datetime" % name)
        elif kind == "date":
            if not is_valid_date_str(v):
                fail("ERR_INVALID_REQUEST", "Field %s must be a YYYY-MM-DD date" % name)
        elif kind == "list":
            if not isinstance(v, list):
                fail("ERR_INVALID_REQUEST", "Field %s must be an array" % name)
        elif kind == "obj":
            if not isinstance(v, dict):
                fail("ERR_INVALID_REQUEST", "Field %s must be an object" % name)
        elif isinstance(kind, tuple) and kind and kind[0] == "enum":
            if not isinstance(v, str) or v not in kind[1]:
                fail("ERR_INVALID_REQUEST", "Field %s has an invalid value" % name)
        # "any" accepts everything


def parse_pagination():
    """Query params limit (default 10, 1..100) and offset (default 0, >=0)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw, 10)
        except (ValueError, TypeError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw, 10)
        except (ValueError, TypeError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(items):
    """Sort by (created_at, insertion seq), slice, and build pagination meta."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta
