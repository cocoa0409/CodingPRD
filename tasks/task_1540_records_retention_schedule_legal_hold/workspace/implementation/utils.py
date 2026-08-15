"""Time handling, calendar arithmetic, decimal helpers, and request-body
validation primitives."""
import re
from calendar import monthrange
from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import invalid_request, invalid_enum


# ---------------------------------------------------------------------------
# Timestamps: ISO 8601 UTC rendered with three fractional digits.
# ---------------------------------------------------------------------------
def fmt_ts(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_dt(value):
    """Parse an ISO 8601 date or datetime into an aware UTC datetime.

    Date-only strings are interpreted at 00:00:00Z on the named calendar day.
    Returns None when unparseable.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    try:
        if _ISO_DATE_RE.match(s):
            d = date.fromisoformat(s)
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        ss = s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s
        dt = datetime.fromisoformat(ss)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def add_months(anchor, months):
    """Calendar month addition with clamping: if the anchor day-of-month
    exceeds the target month's length, clamp to the target's last day."""
    y = anchor.year + (anchor.month - 1 + months) // 12
    m = (anchor.month - 1 + months) % 12 + 1
    d = min(anchor.day, monthrange(y, m)[1])
    return datetime(y, m, d, tzinfo=timezone.utc)


def clamped_fye(year, month, day):
    """Program fiscal-year-end date for a calendar year, clamped to the
    month's length (e.g. Feb 29 in a non-leap year)."""
    return datetime(year, month, min(day, monthrange(year, month)[1]),
                    tzinfo=timezone.utc)


def round_half_up(value, places=0):
    q = Decimal(1) if places == 0 else Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Body validation primitives (priority-4 request shape checks).
# ---------------------------------------------------------------------------
def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            invalid_request("Missing required field: %s" % f)


def check_str(body, field, required=True):
    v = body.get(field)
    if v is None:
        if required:
            invalid_request("Missing required field: %s" % field)
        return None
    if not isinstance(v, str) or v == "":
        invalid_request("Field %s must be a non-empty string" % field)
    return v


def check_int(body, field, required=True, minimum=None, min_exclusive=False):
    v = body.get(field)
    if v is None:
        if required:
            invalid_request("Missing required field: %s" % field)
        return None
    if not is_int(v):
        invalid_request("Field %s must be an integer" % field)
    if minimum is not None:
        if min_exclusive and not v > minimum:
            invalid_request("Field %s must be > %s" % (field, minimum))
        if not min_exclusive and not v >= minimum:
            invalid_request("Field %s must be >= %s" % (field, minimum))
    return v


def check_number(body, field, required=True, minimum=None, min_exclusive=False):
    v = body.get(field)
    if v is None:
        if required:
            invalid_request("Missing required field: %s" % field)
        return None
    if not is_number(v):
        invalid_request("Field %s must be a number" % field)
    if minimum is not None:
        if min_exclusive and not v > minimum:
            invalid_request("Field %s must be > %s" % (field, minimum))
        if not min_exclusive and not v >= minimum:
            invalid_request("Field %s must be >= %s" % (field, minimum))
    return v


def check_bool(body, field, required=True, default=None):
    v = body.get(field)
    if v is None:
        if required:
            invalid_request("Missing required field: %s" % field)
        return default
    if not isinstance(v, bool):
        invalid_request("Field %s must be a boolean" % field)
    return v


def check_enum(body, field, values, required=True, default=None):
    v = body.get(field)
    if v is None:
        if required:
            invalid_request("Missing required field: %s" % field)
        return default
    if not isinstance(v, str) or v not in values:
        invalid_enum("Field %s must be one of %s" % (field, sorted(values)))
    return v


def check_datetime(body, field, required=True):
    v = body.get(field)
    if v is None:
        if required:
            invalid_request("Missing required field: %s" % field)
        return None
    dt = parse_dt(v)
    if dt is None:
        invalid_request("Field %s must be an ISO 8601 date/datetime" % field)
    return dt


def check_str_list(body, field, required=True):
    v = body.get(field)
    if v is None:
        if required:
            invalid_request("Missing required field: %s" % field)
        return None
    if not isinstance(v, list) or any(not isinstance(x, str) or x == "" for x in v):
        invalid_request("Field %s must be a list of strings" % field)
    return v
