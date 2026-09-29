"""Time, logical clock and decimal helpers (PRD sections 2.4 and 2.6)."""

import random
import re
import string
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc

# The logical clock starts at exactly this instant on every boot (PRD 2.4).
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class LogicalClock(object):
    """Test-driven logical clock; never falls back on the wall clock."""

    def __init__(self):
        self._now = CLOCK_EPOCH

    def now(self):
        return self._now

    def set(self, moment):
        self._now = moment

    def reset(self):
        self._now = CLOCK_EPOCH


clock = LogicalClock()


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_datetime(raw):
    """Parse an ISO-8601 instant into an aware UTC datetime, or return None."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not _ISO_RE.match(text):
        return None
    candidate = text
    if candidate[-1] in ("Z", "z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_date(raw):
    """Parse a YYYY-MM-DD calendar date, or return None."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def iso(moment):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.2)."""
    if moment is None:
        return None
    if isinstance(moment, date) and not isinstance(moment, datetime):
        return moment.isoformat()
    aware = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    aware = aware.astimezone(UTC)
    return "%s.%03dZ" % (aware.strftime("%Y-%m-%dT%H:%M:%S"), aware.microsecond // 1000)


def now_wall():
    return datetime.now(tz=UTC)


def plus_days(moment, days):
    return moment + timedelta(days=days)


def plus_hours(moment, hours):
    return moment + timedelta(hours=hours)


def plus_seconds(moment, seconds):
    return moment + timedelta(seconds=seconds)


def whole_seconds_between(start, end):
    """Whole seconds from start to end (may be negative)."""
    return int((end - start).total_seconds())


def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def money(value):
    """Round a Decimal amount to whole cents, half up."""
    return int(round_half_up(Decimal(value), 0))


def bps_of(amount, bps):
    """amount * bps / 10000 rounded half up to whole cents."""
    return money(Decimal(int(amount)) * Decimal(int(bps)) / Decimal(10000))


def ratio(numerator, denominator, places=4):
    """Integer/integer ratio rounded half up once, to `places` digits."""
    if denominator == 0:
        return float(round_half_up(Decimal(0), places))
    value = Decimal(int(numerator)) / Decimal(int(denominator))
    return float(round_half_up(value, places))


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))
