from datetime import datetime, timezone, timedelta


class LogicalClock:
    def __init__(self):
        self._now = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def advance_minutes(self, minutes):
        self._now = self._now + timedelta(minutes=minutes)

    def iso(self):
        return format_iso(self._now)


def format_iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = f"{dt.microsecond // 1000:03d}"
    return f"{s}.{ms}Z"


def parse_iso(s):
    if s is None:
        return None
    if not isinstance(s, str):
        return None
    raw = s
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


CLOCK = LogicalClock()
