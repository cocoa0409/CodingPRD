"""The server-wide logical registry clock (PRD 2.4 / 3.1).

At server startup the clock reads exactly 2026-08-01T00:00:00Z and it holds that
value until it is explicitly moved.  It never falls back to real wall-clock time.
"""
import datetime as _dt
import re

BOOT_INSTANT = _dt.datetime(2026, 8, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d{1,9})?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


class LogicalClock:
    def __init__(self):
        self._now = BOOT_INSTANT

    def now(self):
        return self._now

    def set(self, instant):
        self._now = instant

    def reset(self):
        self._now = BOOT_INSTANT


CLOCK = LogicalClock()


def now():
    return CLOCK.now()


def parse_instant(value):
    """Parse an ISO 8601 UTC instant.  Returns None when the value is not one."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    m = _ISO_RE.match(text)
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    offset = m.group(8)
    try:
        naive = _dt.datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if offset in (None, "Z", "z"):
        return naive.replace(tzinfo=_dt.timezone.utc)
    sign = 1 if offset[0] == "+" else -1
    body = offset[1:].replace(":", "")
    off_hours = int(body[:2])
    off_minutes = int(body[2:4])
    delta = _dt.timedelta(hours=off_hours, minutes=off_minutes) * sign
    return (naive - delta).replace(tzinfo=_dt.timezone.utc)


def format_instant(instant):
    """ISO 8601 UTC with exactly three fractional digits."""
    if instant is None:
        return None
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=_dt.timezone.utc)
    instant = instant.astimezone(_dt.timezone.utc)
    return instant.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (instant.microsecond // 1000)


def plus_seconds(instant, seconds):
    return instant + _dt.timedelta(seconds=seconds)


def plus_days(instant, days):
    """Derived instants are exact multiples of 86400 seconds (PRD 2.8)."""
    return instant + _dt.timedelta(seconds=int(days) * 86400)
