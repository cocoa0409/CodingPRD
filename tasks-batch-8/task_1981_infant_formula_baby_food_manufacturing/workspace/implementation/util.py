"""Datetime, decimal, and validation helpers.

Precision regimes (PRD section 2.5):
- kg quantities: 3 decimal places; allocation arithmetic truncates (floor).
- nutrient concentrations per 100 kcal: 4 decimal places, round half-up.
- percentages and scores: 2 decimal places, round half-up.
"""
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, InvalidOperation

from errors import ApiError, err, ERR_INVALID_REQUEST, ERR_INVALID_RANGE, ERR_INVALID_ENUM

KG_Q = Decimal("0.001")
NUTRIENT_Q = Decimal("0.0001")
PCT_Q = Decimal("0.01")


# ---------------------------------------------------------------- datetimes
def parse_datetime(value, field):
    """Parse an ISO 8601 datetime (accepts trailing Z or numeric offset, and
    date-only strings which are interpreted as midnight UTC)."""
    if not isinstance(value, str) or not value.strip():
        raise err(ERR_INVALID_REQUEST, "Field '%s' must be an ISO 8601 timestamp" % field)
    s = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return dt
        iso = s
        if iso.endswith("Z") or iso.endswith("z"):
            iso = iso[:-1] + "+00:00"
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise err(ERR_INVALID_REQUEST, "Field '%s' must be an ISO 8601 timestamp" % field)


def fmt_dt(dt):
    """Serialize a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return "%s.%03dZ" % (base, dt.microsecond // 1000)


def add_months(dt, months):
    """Calendar-month addition (not 30-day months), clamping the day to the
    target month's last day when necessary."""
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    if m == 12:
        next_month = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month = datetime(y, m + 1, 1, tzinfo=timezone.utc)
    last_day = (next_month - timedelta(days=1)).day
    d = min(dt.day, last_day)
    return dt.replace(year=y, month=m, day=d)


# ---------------------------------------------------------------- decimals
def to_decimal(value, field):
    if isinstance(value, bool):
        raise err(ERR_INVALID_REQUEST, "Field '%s' must be a number" % field)
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            raise err(ERR_INVALID_REQUEST, "Field '%s' must be a number" % field)
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except InvalidOperation:
            raise err(ERR_INVALID_REQUEST, "Field '%s' must be a number" % field)
    raise err(ERR_INVALID_REQUEST, "Field '%s' must be a number" % field)


def floor3(d):
    """Truncate (floor toward zero for positive quantities) to 3 decimal places."""
    return d.quantize(KG_Q, rounding=ROUND_DOWN)


def q2(d):
    return d.quantize(PCT_Q, rounding=ROUND_HALF_UP)


def q3(d):
    return d.quantize(KG_Q, rounding=ROUND_HALF_UP)


def q4(d):
    return d.quantize(NUTRIENT_Q, rounding=ROUND_HALF_UP)


def num(d, places=3):
    """Serialize a Decimal as a JSON number rounded half-up to `places`."""
    if d is None:
        return None
    q = Decimal(1).scaleb(-places)
    return float(d.quantize(q, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------- field validation
def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def _is_empty(v):
    # Only None and empty strings count as "missing": an explicitly supplied
    # empty array is a present value (business rules such as coverage or
    # minimum-length checks decide how to handle it).
    return v is None or (isinstance(v, str) and v.strip() == "")


def require_fields(body, fields):
    for f in fields:
        if f not in body or _is_empty(body.get(f)):
            raise err(ERR_INVALID_REQUEST, "Required field '%s' is missing or empty" % f)


def check_enum(value, allowed, field):
    if value not in allowed:
        raise err(ERR_INVALID_ENUM, "Field '%s' must be one of: %s" % (field, ", ".join(allowed)))
    return value


def check_enum_list(values, allowed, field):
    for v in values:
        if v not in allowed:
            raise err(ERR_INVALID_ENUM, "Field '%s' contains invalid value '%s'" % (field, v))
    return values


def check_int_range(value, lo, hi, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(ERR_INVALID_RANGE, "Field '%s' must be an integer" % field)
    if value < lo or value > hi:
        raise err(ERR_INVALID_RANGE, "Field '%s' must be between %d and %d" % (field, lo, hi))
    return value
