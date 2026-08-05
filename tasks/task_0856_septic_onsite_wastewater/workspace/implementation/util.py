"""Shared utilities: logical clock, datetime rendering/parsing, ids, rounding."""
import calendar
import math
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------- logical clock
DEFAULT_LOGICAL_CLOCK_UTC = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_LOGICAL_CLOCK_UTC}


def now() -> datetime:
    """The server's logical clock. Wall-clock time is NEVER consulted."""
    return _state["now"]


def set_now(value: datetime) -> None:
    _state["now"] = value


def reset_clock() -> None:
    _state["now"] = DEFAULT_LOGICAL_CLOCK_UTC


# ------------------------------------------------------- datetime render/parse
_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def render_dt(value):
    """THE single datetime renderer: ISO 8601 UTC, exactly 3 fractional digits, 'Z'.

    Every datetime that leaves this server -- system stamps, server-computed
    instants and echoed client input alike -- goes through this function.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    millis = value.microsecond // 1000
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year, value.month, value.day,
        value.hour, value.minute, value.second, millis,
    )


def parse_dt(raw):
    """Parse an ISO 8601 instant into an aware UTC datetime; None when invalid."""
    if not isinstance(raw, str):
        return None
    m = _ISO_RE.match(raw.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro,
                      tzinfo=timezone.utc)
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * delta
    return dt


# ------------------------------------------------------------------- identity
def new_id() -> str:
    """Canonical dashed UUID string (never uuid4().hex)."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# ------------------------------------------------------------------- rounding
def dec(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places: int) -> Decimal:
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def num(value):
    """Render a Decimal as a JSON number without exponent noise."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        as_float = float(value)
        if as_float == int(as_float):
            return as_float
        return as_float
    return value


# ------------------------------------------------------------------- calendar
def add_months(anchor: datetime, months: int) -> datetime:
    """Advance by whole calendar months, preserving day-of-month and time-of-day;
    clamp to the last day when the target month is too short."""
    total = anchor.month - 1 + months
    year = anchor.year + total // 12
    month = total % 12 + 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return anchor.replace(year=year, month=month, day=day)


def add_years(anchor: datetime, years: int) -> datetime:
    return add_months(anchor, years * 12)


def add_days(anchor: datetime, days: int) -> datetime:
    return anchor + timedelta(days=days)


def whole_days_between(start: datetime, end: datetime) -> int:
    """Floor of the exact day difference from start to end (negative when past)."""
    return math.floor((end - start).total_seconds() / 86400.0)
