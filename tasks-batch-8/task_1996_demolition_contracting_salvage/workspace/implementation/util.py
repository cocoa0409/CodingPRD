"""Time, decimal, and request-body validation helpers.

All monetary values are integer cents; tonnages are Decimals with at most
three decimal places; rates/ratios round half-up exactly once.
"""

import math
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import err, ERR_VALIDATION

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime, or None if invalid."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def is_date_str(value):
    if not isinstance(value, str) or not DATE_RE.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def round4(d):
    return d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def round1(d):
    return d.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def to_decimal(value):
    return Decimal(str(value))


def has_at_most_3_decimals(d):
    return -d.as_tuple().exponent <= 3


def num(value):
    """Serialize a Decimal/int/float for JSON."""
    if isinstance(value, Decimal):
        return float(value)
    return value


# ---------------------------------------------------------------------------
# Request body validation helpers (all raise ERR_VALIDATION on bad shape).
# ---------------------------------------------------------------------------

def _bad(field):
    raise err(ERR_VALIDATION, f"missing or invalid field: {field}")


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        _bad(field)
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        _bad(field)
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and not (
        isinstance(v, float) and not math.isfinite(v)
    )


def req_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if not _is_int(v):
        _bad(field)
    if minimum is not None and v < minimum:
        _bad(field)
    if maximum is not None and v > maximum:
        _bad(field)
    return v


def req_number(body, field):
    """Returns a Decimal. Generic range violations are ERR_VALIDATION."""
    v = body.get(field)
    if not _is_num(v):
        _bad(field)
    return to_decimal(v)


def opt_number(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not _is_num(v):
        _bad(field)
    return to_decimal(v)


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        _bad(field)
    return v


def req_date_str(body, field):
    v = body.get(field)
    if not is_date_str(v):
        _bad(field)
    return v


def req_datetime(body, field):
    v = body.get(field)
    dt = parse_dt(v)
    if dt is None:
        _bad(field)
    return dt


def req_tons(body, field, allow_zero=False):
    """Tonnage input: number, non-negative (or strictly positive), max 3 decimals."""
    d = req_number(body, field)
    if allow_zero:
        if d < 0:
            _bad(field)
    else:
        if d <= 0:
            _bad(field)
    if not has_at_most_3_decimals(d):
        _bad(field)
    return d
