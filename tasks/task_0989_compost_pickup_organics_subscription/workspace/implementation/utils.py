"""Parsing, decimal math, season/quarter labels, pagination helpers."""

import math
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from flask import request

from errors import bad_request

CENT = Decimal("0.01")
ONE = Decimal("1")

SEASON_MULTIPLIERS = {
    "SPRING": Decimal("1.0"),
    "SUMMER": Decimal("1.2"),
    "FALL": Decimal("1.0"),
    "WINTER": Decimal("0.8"),
}

WEEKDAY_NAMES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def D(value):
    """Decimal from an int/float/str without binary float noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        bad_request("Boolean is not a valid number")
    return Decimal(str(value))


def r2(value):
    """Round half-up to 2 decimal places (kilogram quantities, PRD 2.7)."""
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def money(value):
    """Round half-up to integer cents (PRD 2.7)."""
    return int(D(value).quantize(ONE, rounding=ROUND_HALF_UP))


def num_out(value):
    """Serialize a kg/number field as a JSON number."""
    if value is None:
        return None
    return float(value)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        bad_request("Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            bad_request("Missing required field: " + f)


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        bad_request("Field must be a non-empty string: " + field)
    return v


def require_int(body, field):
    v = body.get(field)
    if not is_int(v):
        bad_request("Field must be an integer: " + field)
    return v


def require_num(body, field):
    v = body.get(field)
    if not is_num(v):
        bad_request("Field must be a number: " + field)
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        bad_request("Field %s must be one of %s" % (field, ", ".join(sorted(allowed))))
    return v


def parse_date(value, field):
    """Parse an ISO date (YYYY-MM-DD); full ISO datetimes reduce to their
    UTC date. Returns a datetime.date or raises ERR_INVALID_REQUEST."""
    if not isinstance(value, str):
        bad_request("Field %s must be an ISO date string" % field)
    s = value.strip()
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        return dt.date()
    except ValueError:
        bad_request("Field %s must be an ISO date string" % field)


def parse_instant(value, field):
    """Parse an ISO 8601 instant to an aware UTC datetime."""
    if not isinstance(value, str):
        bad_request("Field %s must be an ISO 8601 timestamp" % field)
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        bad_request("Field %s must be an ISO 8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def season_of(d):
    m = d.month
    if 3 <= m <= 5:
        return "SPRING"
    if 6 <= m <= 8:
        return "SUMMER"
    if 9 <= m <= 11:
        return "FALL"
    return "WINTER"


def season_label(d):
    return "%d-%s" % (d.year, season_of(d))


def quarter_label(d):
    return "%d-Q%d" % (d.year, (d.month - 1) // 3 + 1)


def pagination_params():
    """limit/offset with defaults 10/0, bounds 1..100 / >=0 (PRD 2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad_request("limit must be an integer")
        if limit < 1 or limit > 100:
            bad_request("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad_request("offset must be an integer")
        if offset < 0:
            bad_request("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total
