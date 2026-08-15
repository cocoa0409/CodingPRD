"""In-memory data store and logical clock.

The store starts EMPTY on every boot — no seeding. All state lives in module
level dicts; the process is restarted by the harness before every test.
"""

from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_CLOCK_START_DEFAULT = "2026-08-01T00:00:00Z"


def _parse_dt(value):
    """Parse an ISO-8601 string (accepts trailing Z) into an aware datetime."""
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    """Format an aware datetime as ISO-8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return "%s.%03dZ" % (base, dt.microsecond // 1000)


class LogicalClock:
    def __init__(self):
        self._now = _parse_dt(_CLOCK_START_DEFAULT)

    def now(self):
        return self._now

    def now_iso(self):
        return fmt_ts(self._now)

    def set(self, value):
        self._now = _parse_dt(value)
        return self._now


CLOCK = LogicalClock()

# ---------------------------------------------------------------------------
# Entity stores — keyed by id. Start empty.
# ---------------------------------------------------------------------------

patients = {}
staff = {}
pools = {}
coverage_windows = {}
on_call_shifts = {}
delegation_grants = {}
portal_messages = {}
time_entries = {}
consent_records = {}
e_visit_claims = {}
escalations = {}
education_notices = {}
