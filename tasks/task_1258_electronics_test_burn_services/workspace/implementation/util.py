"""Time parsing/formatting, numeric helpers, request-body helpers."""
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST

_FRACTION_RE = re.compile(r"T\d{2}:\d{2}:\d{2}(\.\d+)")


def parse_dt(value, field="timestamp"):
    """Parse an ISO-8601 string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be an ISO 8601 string")
    s = value.strip()
    s2 = s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s
    try:
        dt = datetime.fromisoformat(s2)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-05-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_like(dt, ref_raw):
    """Format dt matching the style of the reference raw string (fraction or not)."""
    dt = dt.astimezone(timezone.utc)
    if isinstance(ref_raw, str) and _FRACTION_RE.search(ref_raw):
        return fmt_ms(dt)
    if dt.microsecond:
        return fmt_ms(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def sec(dt):
    """Truncate a datetime to whole seconds (timestamp comparisons use second precision)."""
    return dt.replace(microsecond=0)


def minutes_between(a, b):
    """Exact (b - a) in minutes as a Fraction."""
    d = b - a
    us = d.days * 86400_000_000 + d.seconds * 1_000_000 + d.microseconds
    return Fraction(us, 60_000_000)


def ratio4(fr):
    """Serialize a Fraction rounded to exactly 4 decimal places, round-half-up."""
    val = (Decimal(fr.numerator) / Decimal(fr.denominator)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return float(val)


def num_or_int(fr):
    """Serialize a Fraction as int when integral else float."""
    if fr.denominator == 1:
        return fr.numerator
    return float(fr)


def json_body(required=True):
    data = request.get_json(silent=True)
    if data is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def require_fields(data, *names):
    for n in names:
        if n not in data or data[n] is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field: {n}")


def check_enum(value, allowed, field):
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, f"Invalid value for {field}; allowed: {sorted(allowed)}"
        )
    return value


def check_int(value, field, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be <= {maximum}")
    return value


def check_str(value, field):
    if not isinstance(value, str) or value == "":
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be a non-empty string")
    return value


def check_bool(value, field):
    if not isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be a boolean")
    return value
