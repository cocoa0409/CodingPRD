"""Parsing and numeric helpers. Rounding is ROUND_HALF_UP everywhere; money
is integer cents; no floats are ever used for money."""

import calendar
from datetime import datetime, date, timezone

from decimal import Decimal, ROUND_HALF_UP

from errors import raise_err, ERR_INVALID_REQUEST


def parse_datetime(value):
    """Parse an ISO 8601 datetime; returns aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Strict YYYY-MM-DD parse; returns date or None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def parse_month(value):
    """Strict YYYY-MM parse; returns (year, month) or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    parts = s.split("-")
    if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
        return None
    try:
        y = int(parts[0])
        m = int(parts[1])
    except ValueError:
        return None
    if m < 1 or m > 12:
        return None
    return (y, m)


def month_last_day(year, month):
    return date(year, month, calendar.monthrange(year, month)[1])


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise_err(ERR_INVALID_REQUEST, "Field '%s' is required and must be a string" % field)
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be a string" % field)
    return v


def req_int(body, field):
    v = body.get(field)
    if not is_int(v):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' is required and must be an integer" % field)
    return v


def opt_int(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not is_int(v):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be an integer" % field)
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be one of %s" % (field, sorted(allowed)))
    return v


def req_date(body, field):
    raw = req_str(body, field)
    d = parse_date(raw)
    if d is None:
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be a YYYY-MM-DD date" % field)
    return d


def req_datetime(body, field):
    raw = req_str(body, field)
    dt = parse_datetime(raw)
    if dt is None:
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be an ISO 8601 datetime" % field)
    return dt


def rhu_div(numerator, denominator):
    """Integer division rounded half-up (money math)."""
    q = (Decimal(int(numerator)) / Decimal(int(denominator))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(q)


def rhu_int(value):
    """Round a Decimal to the nearest integer, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rate4(numerator, denominator):
    """Scale-4 fixed-point rate, ROUND_HALF_UP."""
    q = (Decimal(int(numerator)) / Decimal(int(denominator))).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return q
