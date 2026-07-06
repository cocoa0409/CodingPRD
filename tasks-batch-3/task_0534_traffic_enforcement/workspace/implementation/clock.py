from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"


def parse_iso(s):
    """Parse an ISO8601 UTC timestamp into an aware datetime (UTC).

    Accepts a trailing 'Z' or an explicit offset. Raises ValueError on failure.
    """
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso_ms(dt):
    """Format an aware datetime as ISO8601 UTC with exactly 3 fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class LogicalClock:
    def __init__(self):
        self._now = parse_iso(DEFAULT_CLOCK_ISO)

    def now(self):
        return self._now

    def set(self, iso):
        self._now = parse_iso(iso)
