"""Shared helpers: timestamps, field validation, pagination, serializers."""
from datetime import datetime, timezone

import errors
import db


def now_iso():
    """Entity timestamps come from the logical clock, never the wall clock
    (PRD 2.5: the server must not fall back to wall-clock time at any point)."""
    dt = parse_iso(db.clock["current_utc"])
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse_iso(s):
    """Parse an ISO8601 datetime string into an aware datetime. Raises ApiError(400)."""
    if not isinstance(s, str):
        raise errors.invalid_request("Expected ISO8601 datetime string")
    text = s.strip()
    try:
        if text.endswith("Z"):
            dt = datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        raise errors.invalid_request("Invalid ISO8601 datetime: %s" % s)


def clock_now():
    return parse_iso(db.clock["current_utc"])


# ---------- field validators ----------

def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str):
        raise errors.invalid_request("Field '%s' is required and must be a string" % name)
    return v


def opt_str(body, name, default=None):
    v = body.get(name)
    if v is None:
        return default
    if not isinstance(v, str):
        raise errors.invalid_request("Field '%s' must be a string" % name)
    return v


def req_enum(body, name, allowed):
    v = body.get(name)
    if not isinstance(v, str) or v not in allowed:
        raise errors.invalid_request(
            "Field '%s' is required and must be one of %s" % (name, allowed))
    return v


def opt_enum(body, name, allowed, default):
    v = body.get(name)
    if v is None:
        return default
    if not isinstance(v, str) or v not in allowed:
        raise errors.invalid_request(
            "Field '%s' must be one of %s" % (name, allowed))
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(body, name, minimum=None):
    v = body.get(name)
    if not _is_int(v):
        raise errors.invalid_request("Field '%s' is required and must be an integer" % name)
    if minimum is not None and v < minimum:
        raise errors.invalid_request("Field '%s' must be >= %s" % (name, minimum))
    return v


def opt_bool(body, name, default=False):
    v = body.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise errors.invalid_request("Field '%s' must be a boolean" % name)
    return v


def req_number(body, name):
    """Positive number (int or float, not bool)."""
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.invalid_request("Field '%s' is required and must be a number" % name)
    return v


def req_segment_list(body, name):
    v = body.get(name)
    if not isinstance(v, list) or len(v) == 0:
        raise errors.invalid_request("Field '%s' must be a non-empty array" % name)
    for el in v:
        if isinstance(el, bool) or not isinstance(el, (int, float)) or el <= 0:
            raise errors.invalid_request(
                "Every element of '%s' must be a number > 0" % name)
    return v


# ---------- pagination ----------

def pagination_params():
    from flask import request
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items: full sorted list; returns (page_items, total_count)."""
    total = len(items)
    return items[offset:offset + limit], total


def status_filter(items):
    from flask import request
    s = request.args.get("status")
    if s is None:
        return items
    return [x for x in items if x.get("status") == s]


def sort_created(items):
    return sorted(items, key=lambda x: (x["created_at"], x["id"]))


# ---------- common entity helpers ----------

def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def new_entity():
    ts = now_iso()
    return {"id": db.new_id(), "created_at": ts, "updated_at": ts, "version": 1}
