"""The logical clock (PRD 2.4).

No server-written timestamp is ever read from the host wall clock.  The clock
starts at 2026-08-01T00:00:00Z and only moves when an operator moves it.
"""

from datetime import datetime, timezone

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock(object):
    def __init__(self):
        self._current = CLOCK_EPOCH

    def now(self):
        return self._current

    def set(self, moment):
        self._current = moment.astimezone(timezone.utc)
        return self._current

    def reset(self):
        self._current = CLOCK_EPOCH


clock = LogicalClock()


def fmt(moment):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if moment is None:
        return None
    moment = moment.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year,
        moment.month,
        moment.day,
        moment.hour,
        moment.minute,
        moment.second,
        moment.microsecond // 1000,
    )


def parse_iso(raw):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)
