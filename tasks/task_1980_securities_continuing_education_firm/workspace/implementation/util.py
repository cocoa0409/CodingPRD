"""Datetime / decimal / input-validation helpers.

All timestamps inside the system are timezone-aware UTC datetimes truncated to
whole seconds (PRD: comparisons at one-second precision; output renders with
three fractional digits, i.e. always ".000Z" for derived values).
"""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from errors import ApiError, ERR_INVALID_REQUEST

CENT = Decimal("0.01")
ONE = Decimal("1")


def fmt_dt(dt):
    """Serialize a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_dt(value, field="timestamp"):
    """Parse an ISO 8601 string to an aware UTC datetime truncated to seconds."""
    if not isinstance(value, str) or not value.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field '%s' must be an ISO 8601 datetime string" % field)
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field '%s' is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def to_decimal(value, field="number"):
    """Coerce a JSON number (or numeric string) to Decimal without float error."""
    if value is None or isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be a number" % field)
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except (InvalidOperation, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "Field '%s' must be a number" % field)
    raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be a number" % field)


def require_int(value, field):
    """Require an integer JSON value (bool excluded)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be an integer" % field)
    return value


def require_str(value, field):
    if not isinstance(value, str) or value == "":
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field '%s' is required and must be a non-empty string" % field)
    return value


def require_enum(value, field, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field '%s' must be one of %s" % (field, sorted(allowed)))
    return value


def decimal_places(d):
    """Number of decimal places of a Decimal (negative exponent)."""
    return -d.as_tuple().exponent


def q2(d):
    """Quantize to two decimal places, round half up."""
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def round_to_half(x):
    """Round half up to the nearest 0.5: round_half_up(x * 2) / 2."""
    return (x * 2).quantize(ONE, rounding=ROUND_HALF_UP) / 2


def num(d):
    """JSON-friendly rendering of a Decimal: int when integral, else float."""
    if d is None:
        return None
    if not isinstance(d, Decimal):
        return d
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def view(rec):
    """Serialize a stored record: drop internal keys, render datetimes/Decimals."""
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        elif isinstance(v, Decimal):
            out[k] = num(v)
        else:
            out[k] = v
    return out
