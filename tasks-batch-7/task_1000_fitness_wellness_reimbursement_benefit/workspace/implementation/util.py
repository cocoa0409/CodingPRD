"""Datetime, decimal, and quarter helpers."""
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import err, ERR_INVALID_REQUEST

UTC = timezone.utc


def parse_dt(value):
    """Parse an ISO-8601 datetime (accepts date-only, 'Z', offsets, fractional
    seconds). Returns an aware UTC datetime. Raises ERR_INVALID_REQUEST."""
    if not isinstance(value, str) or not value.strip():
        raise err(ERR_INVALID_REQUEST, 400, f"malformed datetime: {value!r}")
    s = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)
        else:
            iso = s
            if iso.endswith(("Z", "z")):
                iso = iso[:-1] + "+00:00"
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            else:
                dt = dt.astimezone(UTC)
    except (ValueError, OverflowError):
        raise err(ERR_INVALID_REQUEST, 400, f"malformed datetime: {value!r}")
    return dt


def fmt_ts(dt):
    """System timestamp format: ISO 8601 UTC with exactly three fractional digits."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def quarter_key_of(dt):
    q = (dt.month - 1) // 3 + 1
    return f"{dt.year}-Q{q}"


def rhu(value):
    """Round half up to the nearest integer cent. Accepts int/Decimal/str."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(value):
    """Round half up to two decimal places, returned as float."""
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def month_range(yyyymm):
    """'YYYY-MM' -> (month_start, next_month_start) aware datetimes."""
    if not isinstance(yyyymm, str) or not re.fullmatch(r"\d{4}-\d{2}", yyyymm):
        raise err(ERR_INVALID_REQUEST, 400, f"malformed period_yyyymm: {yyyymm!r}")
    y, m = int(yyyymm[:4]), int(yyyymm[5:7])
    if not (1 <= m <= 12):
        raise err(ERR_INVALID_REQUEST, 400, f"malformed period_yyyymm: {yyyymm!r}")
    start = datetime(y, m, 1, tzinfo=UTC)
    nxt = datetime(y + 1, 1, 1, tzinfo=UTC) if m == 12 else datetime(y, m + 1, 1, tzinfo=UTC)
    return start, nxt


def add_years(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:  # Feb 29 -> Feb 28
        return dt.replace(year=dt.year + years, day=28)


# ---------------------------------------------------------------------------
# Request-shape validation helpers
# ---------------------------------------------------------------------------

def body_json():
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, 400, "request body must be a JSON object")
    return data


def req(body, name):
    if name not in body or body[name] is None:
        raise err(ERR_INVALID_REQUEST, 400, f"required field missing: {name}")
    return body[name]


def opt(body, name, default=None):
    v = body.get(name, default)
    return default if v is None else v


def as_str(v, name):
    if not isinstance(v, str) or not v:
        raise err(ERR_INVALID_REQUEST, 400, f"field must be a non-empty string: {name}")
    return v


def as_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, 400, f"field must be an integer: {name}")
    return v


def as_num(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_INVALID_REQUEST, 400, f"field must be a number: {name}")
    return v


def as_list(v, name):
    if not isinstance(v, list):
        raise err(ERR_INVALID_REQUEST, 400, f"field must be an array: {name}")
    return v


def check_enum(v, allowed, name):
    from errors import ERR_INVALID_ENUM
    if v not in allowed:
        raise err(ERR_INVALID_ENUM, 400, f"field {name} carries an undeclared value: {v!r}")
    return v


def check_positive(v, name):
    from errors import ERR_INVALID_AMOUNT
    if v <= 0:
        raise err(ERR_INVALID_AMOUNT, 400, f"field must be positive: {name}")
    return v


def check_nonnegative(v, name):
    from errors import ERR_INVALID_AMOUNT
    if v < 0:
        raise err(ERR_INVALID_AMOUNT, 400, f"field must be zero or greater: {name}")
    return v
