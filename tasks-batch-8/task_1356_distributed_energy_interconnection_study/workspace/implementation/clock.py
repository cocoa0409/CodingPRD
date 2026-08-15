"""Logical clock (PRD section 2.6). Starts at exactly 2026-08-01T00:00:00Z and
never falls back to wall-clock time. Advanced only via POST /_clock/set_current_utc.
All clock-relative deadline evaluations read this clock."""
from datetime import datetime, timezone

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def parse_iso(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    else:
        raise ValueError("not an ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix
    (PRD section 2.4: created_at / updated_at carry three fractional digits)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def format_clock(dt):
    """Render a clock-derived domain timestamp (issued_at, execution_deadline).
    Whole seconds when the instant has no sub-second component (matching the
    canonical rendering of the logical clock default, '2026-08-01T00:00:00Z');
    otherwise three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return format_ms(dt)


class _Clock:
    def __init__(self):
        self._raw = DEFAULT_CLOCK
        self._now = parse_iso(DEFAULT_CLOCK)

    def now(self):
        return self._now

    def raw(self):
        """The exact string the clock was last set to (or the startup default)."""
        return self._raw

    def now_ms(self):
        return format_ms(self._now)

    def set(self, raw):
        self._now = parse_iso(raw)
        self._raw = raw
        return self._now


CLOCK = _Clock()
