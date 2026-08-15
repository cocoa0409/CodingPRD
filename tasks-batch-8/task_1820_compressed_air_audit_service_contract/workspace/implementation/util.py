"""Parsing, validation, decimal and date helpers."""

import calendar
import re
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import invalid_request
import store

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def round_half_up(x):
    """Decimal -> whole integer, ROUND_HALF_UP."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(v):
    """Exact Decimal from a JSON number (avoids float binary noise)."""
    return Decimal(str(v))


def parse_date(s):
    """Strict ISO YYYY-MM-DD -> date, or None."""
    if not isinstance(s, str) or not DATE_RE.match(s):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_iso_datetime(s):
    """Lenient ISO 8601 datetime -> aware UTC datetime at second precision."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if not t:
        return None
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def add_months(d, months):
    """d + months calendar months, same day-of-month (clamped to month end)."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def body_or_empty():
    """Return the JSON request body as a dict; {} when absent/not JSON."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_field(body, name):
    if name not in body or body[name] is None:
        raise invalid_request(f"Missing required field: {name}")
    return body[name]


def req_str(body, name):
    v = req_field(body, name)
    if not isinstance(v, str):
        raise invalid_request(f"Field {name} must be a string")
    return v


def req_int(body, name):
    v = req_field(body, name)
    if not _is_int(v):
        raise invalid_request(f"Field {name} must be an integer")
    return v


def req_num(body, name):
    v = req_field(body, name)
    if not _is_num(v):
        raise invalid_request(f"Field {name} must be a number")
    return v


def req_bool(body, name):
    v = req_field(body, name)
    if not isinstance(v, bool):
        raise invalid_request(f"Field {name} must be a boolean")
    return v


def req_date(body, name):
    v = req_field(body, name)
    d = parse_date(v)
    if d is None:
        raise invalid_request(f"Field {name} must be an ISO YYYY-MM-DD date")
    return d


def req_enum(body, name, allowed):
    v = req_str(body, name)
    if v not in allowed:
        raise invalid_request(f"Field {name} must be one of {sorted(allowed)}")
    return v


def opt_int(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not _is_int(v):
        raise invalid_request(f"Field {name} must be an integer")
    return v


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str):
        raise invalid_request(f"Field {name} must be a string")
    return v


def req_list_of_str(body, name):
    v = req_field(body, name)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise invalid_request(f"Field {name} must be an array of strings")
    return v


def parse_pagination():
    """limit/offset per response_envelope: default 10/0, limit clamped 1..100."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("Query parameter limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("Query parameter offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def sort_and_page(items, limit, offset):
    """created_at ASC default sort, then slice."""
    ordered = sorted(items, key=lambda r: r["created_at"])
    total = len(ordered)
    return ordered[offset:offset + limit], total


def public(res):
    """Resources are stored JSON-native; return a shallow copy."""
    return dict(res)
