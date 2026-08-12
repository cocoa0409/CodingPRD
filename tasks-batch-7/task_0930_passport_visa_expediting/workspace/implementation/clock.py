"""The logical clock and the SINGLE instant-rendering helper (PRD 2.4, 2.5).

Every server-written instant, every echoed caller-supplied instant and the
envelope timestamp go through render_instant() so no code path can diverge on
fractional-digit rendering.
"""
import datetime as _dt

from constants import DEFAULT_CLOCK_UTC

UTC = _dt.timezone.utc

_DEFAULT = _dt.datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)


class _Clock:
    def __init__(self):
        self.current = _DEFAULT

    def now(self):
        return self.current

    def set(self, instant):
        self.current = instant.astimezone(UTC)
        return self.current

    def reset(self):
        self.current = _DEFAULT


CLOCK = _Clock()


def now():
    return CLOCK.now()


def today():
    return CLOCK.now().date()


def parse_instant(value):
    """Parse any legal ISO-8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_date(value):
    """Parse a plain YYYY-MM-DD calendar date. Returns a date or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10:
        return None
    try:
        return _dt.date.fromisoformat(text)
    except ValueError:
        return None


def render_instant(value):
    """THE uniform instant renderer: ISO-8601 UTC, exactly 3 fractional digits, Z."""
    if value is None:
        return None
    if isinstance(value, str):
        parsed = parse_instant(value)
        if parsed is None:
            return value
        value = parsed
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    value = value.astimezone(UTC)
    millis = value.microsecond // 1000
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        millis,
    )


def render_date(value):
    """Plain YYYY-MM-DD calendar date rendering (no time, no zone)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


DEFAULT_CLOCK_INSTANT = DEFAULT_CLOCK_UTC
