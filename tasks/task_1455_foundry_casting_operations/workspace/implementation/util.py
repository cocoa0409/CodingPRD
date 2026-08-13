"""Numeric (Decimal, round-half-up per PRD 2.7), time, and payload helpers."""

import calendar
from datetime import datetime, timezone

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from errors import fail

D0 = Decimal("0")
CENT = Decimal("0.01")
TENTH = Decimal("0.1")
TEN4 = Decimal("0.0001")


def D(v, field="value"):
    """Coerce a JSON number to Decimal (reject bools / non-numerics)."""
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number" % field)
    try:
        return Decimal(str(v))
    except Exception:
        fail("ERR_INVALID_REQUEST", "%s must be a number" % field)


def q2(x):
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def q1(x):
    return x.quantize(TENTH, rounding=ROUND_HALF_UP)


def q4(x):
    return x.quantize(TEN4, rounding=ROUND_HALF_UP)


def q0(x):
    return x.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def ceil_int(x):
    return int(x.to_integral_value(rounding=ROUND_CEILING))


# ---------------------------------------------------------------------------
# Time helpers — timestamps compared at second precision (PRD 2.7); rendered
# ISO 8601 UTC with three fractional digits (PRD 2.5).
# ---------------------------------------------------------------------------

def render_ts(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(v, field):
    if not isinstance(v, str):
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 string" % field)
    s = v.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "%s is not a valid ISO 8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def add_months(dt, months):
    total = (dt.year * 12 + (dt.month - 1)) + int(months)
    y, m0 = divmod(total, 12)
    m = m0 + 1
    d = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


# ---------------------------------------------------------------------------
# Payload validation helpers (ERR_INVALID_REQUEST on malformed input).
# ---------------------------------------------------------------------------

def body_dict(body):
    if body is None:
        return {}
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return body


def req(body, name):
    if name not in body or body[name] is None:
        fail("ERR_INVALID_REQUEST", "missing required field: %s" % name)
    return body[name]


def opt(body, name, default=None):
    v = body.get(name, default)
    return default if v is None else v


def as_str(v, field):
    if not isinstance(v, str) or v == "":
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty string" % field)
    return v


def as_int(v, field):
    if isinstance(v, bool) or not isinstance(v, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    return v


def as_pos_int(v, field):
    v = as_int(v, field)
    if v <= 0:
        fail("ERR_INVALID_REQUEST", "%s must be a positive integer" % field)
    return v


def as_nonneg_int(v, field):
    v = as_int(v, field)
    if v < 0:
        fail("ERR_INVALID_REQUEST", "%s must be zero or greater" % field)
    return v


def as_num(v, field):
    return D(v, field)


def as_nonneg_num(v, field):
    d = D(v, field)
    if d < 0:
        fail("ERR_INVALID_REQUEST", "%s must not be negative" % field)
    return d


def as_enum(v, field, allowed):
    if not isinstance(v, str) or v not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (field, sorted(allowed)))
    return v
