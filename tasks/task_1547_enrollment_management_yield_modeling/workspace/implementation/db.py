"""In-memory data store. Empty at boot; all state built via API calls."""
import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


def _parse_iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _fmt_ts(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits and Z."""
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = f"{dt.microsecond // 1000:03d}"
    return f"{base}.{ms}Z"


class Clock:
    def __init__(self):
        self._current = _parse_iso(_DEFAULT_CLOCK_ISO)

    def now(self):
        return self._current

    def set(self, dt):
        self._current = dt

    def iso(self):
        return _fmt_ts(self._current)


clock = Clock()


def now_iso():
    return clock.iso()


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class Store:
    def __init__(self):
        self.cycles = {}
        self.programs = {}
        self.applicants = {}
        self.applications = {}
        self.reviews = {}
        self.aid_offers = {}
        self.deposits = {}
        self.waitlist_entries = {}
        self.interventions = {}

    def reset(self):
        self.__init__()


store = Store()
