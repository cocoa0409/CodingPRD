"""Decimal / timestamp helpers.

All numeric work uses decimal.Decimal with ROUND_HALF_UP (PRD 2.5).
All timestamps are ISO 8601 UTC with exactly three fractional digits.
"""
import datetime
import math
import random
import string
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

UTC = datetime.timezone.utc

D0 = Decimal("0")


def dec(value):
    """Coerce a JSON scalar into Decimal without binary float noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise InvalidOperation("bool is not numeric")
    return Decimal(str(value))


def q(value, places):
    """Round half-up to `places` decimal places."""
    if not isinstance(value, Decimal):
        value = dec(value)
    exp = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    return value.quantize(exp, rounding=ROUND_HALF_UP)


def q0(value):
    """Round half-up to a whole number, returned as int (money in cents)."""
    return int(q(value, 0))


def ceil_dec(value):
    if not isinstance(value, Decimal):
        value = dec(value)
    return int(math.ceil(value))


def floor_dec(value):
    if not isinstance(value, Decimal):
        value = dec(value)
    return int(math.floor(value))


def decimal_places(value):
    text = str(value)
    if "." not in text:
        return 0
    return len(text.split(".", 1)[1].rstrip())


def fmt_ts(moment):
    """ISO 8601 UTC with exactly three fractional digits, Z suffix."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    moment = moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moment.microsecond // 1000)


def parse_ts(text):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    candidate = raw
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def hours_between(start, end):
    """Exact elapsed hours as Decimal (unrounded)."""
    seconds = Decimal(str((end - start).total_seconds()))
    return seconds / Decimal("3600")


PEAK_START_HOUR = 8
PEAK_END_HOUR = 20


def band_hours(start, end):
    """Split [start, end) into peak / off-peak hours (PRD 3.8).

    The peak band is 08:00 inclusive to 20:00 exclusive UTC. A window spanning
    midnight is split per UTC calendar day before banding. Both totals are
    rounded half-up to four decimal places.
    """
    peak_seconds = Decimal("0")
    off_seconds = Decimal("0")
    if end <= start:
        return Decimal("0.0000"), Decimal("0.0000")
    cursor = start
    while cursor < end:
        day_end = datetime.datetime.combine(
            cursor.date() + datetime.timedelta(days=1),
            datetime.time(0, 0, 0),
            tzinfo=UTC,
        )
        segment_end = min(day_end, end)
        peak_lo = datetime.datetime.combine(
            cursor.date(), datetime.time(PEAK_START_HOUR, 0, 0), tzinfo=UTC
        )
        peak_hi = datetime.datetime.combine(
            cursor.date(), datetime.time(PEAK_END_HOUR, 0, 0), tzinfo=UTC
        )
        overlap_lo = max(cursor, peak_lo)
        overlap_hi = min(segment_end, peak_hi)
        overlap = Decimal("0")
        if overlap_hi > overlap_lo:
            overlap = Decimal(str((overlap_hi - overlap_lo).total_seconds()))
        total = Decimal(str((segment_end - cursor).total_seconds()))
        peak_seconds += overlap
        off_seconds += total - overlap
        cursor = segment_end
    peak = q(peak_seconds / Decimal("3600"), 4)
    off = q(off_seconds / Decimal("3600"), 4)
    return peak, off
