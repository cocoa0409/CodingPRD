"""Time handling, payload validation, and pagination helpers."""

import re
from datetime import datetime, date, timezone

from flask import request

from errors import invalid_request


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def fmt_dt(dt):
    """Serialize a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value, field):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        invalid_request("%s must be an ISO 8601 datetime string" % field)
    text = value.strip()
    try:
        if text.endswith("Z"):
            dt = datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(text)
    except ValueError:
        invalid_request("%s is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field):
    """Parse an ISO 8601 calendar date string."""
    if not isinstance(value, str):
        invalid_request("%s must be an ISO 8601 date string" % field)
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        invalid_request("%s is not a valid ISO 8601 date" % field)


def wallclock_iso():
    """Wall-clock UTC timestamp with three fractional digits (for meta)."""
    return fmt_dt(datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Payload validation
# ---------------------------------------------------------------------------

def get_payload(required=True):
    """Return the JSON request body as a dict, or raise ERR_INVALID_REQUEST."""
    data = request.get_json(silent=True)
    if data is None:
        if required:
            invalid_request("request body must be a JSON object")
        return {}
    if not isinstance(data, dict):
        invalid_request("request body must be a JSON object")
    return data


def check_unknown(data, allowed):
    extra = [k for k in data.keys() if k not in allowed]
    if extra:
        invalid_request("unknown payload field(s): %s" % ", ".join(sorted(extra)))


def require(data, field):
    if field not in data or data[field] is None:
        invalid_request("missing required field: %s" % field)
    return data[field]


def as_str(value, field):
    if not isinstance(value, str):
        invalid_request("%s must be a string" % field)
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        invalid_request("%s must be a boolean" % field)
    return value


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        invalid_request("%s must be an integer" % field)
    return value


def as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid_request("%s must be a number" % field)
    return value


def as_str_array(value, field):
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        invalid_request("%s must be an array of strings" % field)
    return list(value)


def as_enum(value, field, members):
    if not isinstance(value, str) or value not in members:
        invalid_request("%s must be one of: %s" % (field, ", ".join(members)))
    return value


# ---------------------------------------------------------------------------
# Pagination (limit/offset; defaults 10/0, limit min 1 max 100)
# ---------------------------------------------------------------------------

def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            invalid_request("limit must be an integer")
        if str(limit) != raw_limit.strip() and not re.fullmatch(r"\+?\d+", raw_limit.strip()):
            invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid_request("offset must be an integer")
        if str(offset) != raw_offset.strip() and not re.fullmatch(r"\+?\d+", raw_offset.strip()):
            invalid_request("offset must be an integer")
        if offset < 0:
            invalid_request("offset must be >= 0")
    return limit, offset


def page_of(records):
    """Sort by (created_at, insertion seq) ascending and apply pagination."""
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    return ordered[offset:offset + limit], total, limit, offset


def query_enum(name, members):
    """Validate an optional enum-typed query filter; returns value or None."""
    value = request.args.get(name)
    if value is None:
        return None
    if value not in members:
        invalid_request("%s must be one of: %s" % (name, ", ".join(members)))
    return value
