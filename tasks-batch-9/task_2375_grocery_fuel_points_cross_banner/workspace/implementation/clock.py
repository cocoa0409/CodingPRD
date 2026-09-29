"""Logical UTC clock (PRD 2.7) and timestamp helpers (PRD 2.2 / 2.6)."""
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_NOW}

MIN_DT = datetime(1, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt.astimezone(timezone.utc)
    return _state["now"]


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000
    )


def now_str():
    return fmt(now())


_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_ts(value):
    """Parse an ISO-8601 UTC timestamp. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _TS_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tzs = m.group(8)
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if tzs is None or tzs in ("Z", "z"):
        return naive.replace(tzinfo=timezone.utc)
    sign = 1 if tzs[0] == "+" else -1
    body = tzs[1:].replace(":", "")
    offset_minutes = sign * (int(body[:2]) * 60 + int(body[2:4]))
    from datetime import timedelta
    return (naive - timedelta(minutes=offset_minutes)).replace(tzinfo=timezone.utc)


def rhu(value, places=0):
    """ROUND_HALF_UP quantize (PRD 2.6)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exp = Decimal(1).scaleb(-places)
    return value.quantize(exp, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))
