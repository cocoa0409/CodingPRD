"""Shared helpers: ids, timestamps, the logical clock, calendar math, rounding.

Nothing in the implementation reads the machine wall clock for a business rule;
every domain "now" comes from the logical CLOCK (PRD 2.4). The wall clock is
used only for the meta.api_request_timestamp envelope field.
"""
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def wall_now_ts() -> str:
    """Envelope timestamp: ISO 8601 UTC with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# ISO 8601 parsing / rendering
# ---------------------------------------------------------------------------

_ISO_INSTANT = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_instant(text):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None."""
    if not isinstance(text, str):
        return None
    m = _ISO_INSTANT.match(text.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * delta
    return dt.replace(tzinfo=timezone.utc)


def render_instant(dt):
    """Server-written instant: YYYY-MM-DDTHH:MM:SS.mmmZ (three digits always)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}.{:03d}Z".format(
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_date(text):
    """Parse a caller-supplied YYYY-MM-DD calendar date, or None."""
    if not isinstance(text, str):
        return None
    m = _ISO_DATE.match(text.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def is_valid_date_string(text) -> bool:
    return parse_date(text) is not None


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


class LogicalClock:
    def __init__(self):
        self._dt = parse_instant(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def set(self, to: datetime) -> datetime:
        self._dt = to
        return self._dt


CLOCK = LogicalClock()


def now() -> datetime:
    return CLOCK.now()


# ---------------------------------------------------------------------------
# Age in full calendar years (PRD 3.2): a patient whose birthday falls on the
# scheduled date counts as having turned that age.
# ---------------------------------------------------------------------------

def age_at(dob: date, at: datetime) -> int:
    at_date = at.date()
    years = at_date.year - dob.year
    if (at_date.month, at_date.day) < (dob.month, dob.day):
        years -= 1
    return years


# ---------------------------------------------------------------------------
# Rates: exactly one decimal place, round-half-up (PRD 2.8)
# ---------------------------------------------------------------------------

def rate_half_up_1dp(numerator, denominator):
    """round_half_up(100 * numerator / denominator, 1) as a float, or None."""
    if denominator == 0:
        return None
    val = (Decimal(100) * Decimal(int(numerator)) / Decimal(int(denominator)))
    return float(val.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def mean_half_up_1dp(values):
    if not values:
        return None
    total = Decimal(0)
    for v in values:
        total += Decimal(int(v))
    val = total / Decimal(len(values))
    return float(val.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp_decimal(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
