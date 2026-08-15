"""Parsing, pagination, period and calendar-month arithmetic utilities."""
import re
import uuid
from calendar import monthrange
from datetime import datetime, date, timezone, timedelta

from flask import request

import errors

_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def new_id():
    return str(uuid.uuid4())


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require_field(body, name):
    if not isinstance(body, dict) or name not in body or body[name] is None:
        raise errors.invalid_request("Missing required field: %s" % name)
    return body[name]


def require_int(body, name):
    v = require_field(body, name)
    if not is_int(v):
        raise errors.invalid_request("Field %s must be an integer" % name)
    return v


def optional_int(body, name, default=None):
    if not isinstance(body, dict) or name not in body:
        return default
    v = body[name]
    if v is None:
        return None
    if not is_int(v):
        raise errors.invalid_request("Field %s must be an integer" % name)
    return v


def parse_period(value, error=None):
    """Validate a YYYY-MM string; returns the string unchanged."""
    if not isinstance(value, str) or not _PERIOD_RE.match(value):
        raise (error or errors.invalid_period())
    return value


def period_key(period):
    y, m = period.split("-")
    return (int(y), int(m))


def period_add(period, months):
    """Whole-month arithmetic on a YYYY-MM period string."""
    y, m = period_key(period)
    idx = y * 12 + (m - 1) + months
    return "%04d-%02d" % (idx // 12, idx % 12 + 1)


def add_months(d, months):
    """Add calendar months to a date, clamping the day to the month end."""
    idx = d.year * 12 + (d.month - 1) + months
    y, m = idx // 12, idx % 12 + 1
    day = min(d.day, monthrange(y, m)[1])
    return date(y, m, day)


def parse_datetime(value):
    """Parse an ISO 8601 datetime; returns an aware UTC datetime."""
    if not isinstance(value, str):
        raise errors.invalid_request("Expected an ISO 8601 datetime string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1]).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        raise errors.invalid_request("Malformed ISO 8601 datetime: %s" % value)
    return dt.astimezone(timezone.utc)


def parse_pagination():
    """limit (default 10, min 1, max 100), offset (default 0)."""
    args = request.args
    try:
        limit = int(args.get("limit", 10))
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise errors.invalid_request("limit and offset must be integers")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items):
    """Slice a pre-sorted list and build the pagination meta fields."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def deadline_plus_days(sent_at, days):
    return sent_at + timedelta(days=days)
