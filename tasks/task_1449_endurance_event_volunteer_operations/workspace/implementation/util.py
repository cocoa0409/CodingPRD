"""Time / parsing / decimal helpers."""
import re
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store
import errors


def utc_now_iso():
    """Wall-clock timestamp for meta timestamps only (3 fractional digits, Z)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def logical_now_iso():
    """The server logical clock (never wall clock)."""
    return store.clock_now_iso


def logical_now():
    return parse_dt(store.clock_now_iso)


def set_logical_clock(to_iso8601):
    store.clock_now_iso = normalize_iso(to_iso8601)
    return store.clock_now_iso


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(value):
    """Parse an ISO-8601 datetime into an aware UTC datetime. Raises ApiError on bad input."""
    if not isinstance(value, str):
        raise errors.invalid_request(f"Expected ISO8601 datetime string, got {type(value).__name__}")
    s = value.strip()
    m = _ISO_RE.match(s)
    if not m:
        raise errors.invalid_request(f"Invalid ISO8601 datetime: {value!r}")
    year, month, day, hh, mm, ss = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micro = 0
    if frac:
        digits = frac[1:]
        micro = int((digits + "000000")[:6])
    tz = m.group(8)
    offset = timedelta(0)
    if tz and tz != "Z":
        sign = 1 if tz[0] == "+" else -1
        tz_digits = tz[1:].replace(":", "")
        oh, om = int(tz_digits[:2]), int(tz_digits[2:4])
        offset = sign * timedelta(hours=oh, minutes=om)
    try:
        dt = datetime(year, month, day, hh, mm, ss, micro, tzinfo=timezone(offset))
    except ValueError as e:
        raise errors.invalid_request(f"Invalid ISO8601 datetime: {value!r} ({e})")
    return dt.astimezone(timezone.utc)


def normalize_iso(value):
    return format_iso(parse_dt(value))


def format_iso(dt):
    """Format an aware UTC datetime as ISO8601 with Z, preserving microseconds if present."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        base = dt.strftime("%Y-%m-%dT%H:%M:%S")
        frac = f"{dt.microsecond:06d}".rstrip("0")
        return f"{base}.{frac}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value):
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        raise errors.invalid_request(f"Invalid ISO date (YYYY-MM-DD): {value!r}")
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError as e:
        raise errors.invalid_request(f"Invalid ISO date: {value!r} ({e})")


def compute_age_years(dob, event_start_dt):
    """Whole years between date_of_birth and event_start_at's UTC calendar date.
    A birthday falling exactly on the event date counts as reached."""
    d = event_start_dt.date()
    b = dob
    age = d.year - b.year
    if (d.month, d.day) < (b.month, b.day):
        age -= 1
    return age


def round_half_up(value, places=0):
    """Decimal round-half-up. value may be Decimal/int/str. Returns Decimal."""
    q = Decimal(1).scaleb(-places)  # 1, 0.1, 0.01, ...
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def dec_to_number(d):
    """Serialize a Decimal as int when integral else float with exact decimal value."""
    d = Decimal(d)
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# --- request body field extraction helpers ---

def get_body():
    from flask import request
    if not request.is_json:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return data


def require_field(body, name):
    if name not in body or body[name] is None:
        raise errors.invalid_request(f"Missing required field: {name}")
    return body[name]


def optional_field(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return body[name]


def as_string(value, name):
    if not isinstance(value, str):
        raise errors.invalid_request(f"Field {name} must be a string.")
    return value


def as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.invalid_request(f"Field {name} must be an integer.")
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise errors.invalid_request(f"Field {name} must be a boolean.")
    return value


def as_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise errors.invalid_request(f"Field {name} must be a number.")
    return value


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise errors.invalid_request(
            f"Field {name} must be one of {sorted(allowed)}.")
    return value
