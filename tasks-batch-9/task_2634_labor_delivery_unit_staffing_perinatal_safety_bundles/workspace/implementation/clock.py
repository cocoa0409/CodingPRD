"""The logical unit clock plus every time / rounding helper (PRD 2.5, 2.8)."""

import datetime as _dt
from decimal import Decimal, ROUND_HALF_UP

UTC = _dt.timezone.utc
BOOT_INSTANT = _dt.datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Clock(object):
    def __init__(self):
        self.now = BOOT_INSTANT
        self.previous = None

    def reset(self):
        self.now = BOOT_INSTANT
        self.previous = None

    def set(self, instant):
        self.previous = self.now
        self.now = instant
        return self.now


CLOCK = Clock()


def now():
    return CLOCK.now


def parse_dt(raw):
    """Parse an ISO-8601 instant. Returns None when unparseable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("z") or text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        value = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_date(raw):
    if not isinstance(raw, str):
        return None
    try:
        return _dt.date.fromisoformat(raw.strip())
    except ValueError:
        return None


def fmt_dt(value):
    if value is None:
        return None
    value = value.astimezone(UTC)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (value.microsecond // 1000)) + "Z"


def day_of(value):
    if value is None:
        return None
    return value.astimezone(UTC).date().isoformat()


def plus_minutes(anchor, minutes):
    return anchor + _dt.timedelta(minutes=minutes)


def plus_hours(anchor, hours):
    return anchor + _dt.timedelta(hours=hours)


def plus_days(anchor, days):
    return anchor + _dt.timedelta(days=days)


def whole_minutes_between(start, end):
    """Elapsed whole minutes: total seconds // 60, fraction discarded (PRD 2.8)."""
    seconds = int((end - start).total_seconds())
    if seconds < 0:
        # truncate toward zero for negatives as well
        return -((-seconds) // 60)
    return seconds // 60


def round_half_up(value, places):
    """Round half away from zero at `places` decimals; returns a float."""
    if value is None:
        return None
    quant = Decimal(1).scaleb(-places)
    dec = Decimal(repr(float(value))).quantize(quant, rounding=ROUND_HALF_UP)
    return float(dec)


def one_dp(value):
    return round_half_up(value, 1)


def two_dp(value):
    return round_half_up(value, 2)


def four_dp(value):
    return round_half_up(value, 4)
