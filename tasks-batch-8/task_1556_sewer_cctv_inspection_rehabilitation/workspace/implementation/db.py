"""In-memory data store. Empty at boot; tests build all state via the API."""
import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_INITIAL_CLOCK_ISO = "2026-08-01T00:00:00Z"


def _parse_iso(value):
    """Parse ISO 8601 datetime. Accepts trailing 'Z' and fractional seconds."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_iso(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits + 'Z'."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}"
    return ms + "Z"


class _Clock:
    def __init__(self):
        self._now = _parse_iso(_INITIAL_CLOCK_ISO)

    def now(self):
        return self._now

    def now_iso(self):
        return _format_iso(self._now)

    def set(self, value):
        self._now = _parse_iso(value)


clock = _Clock()


def new_id():
    return str(uuid.uuid4())


def now_dt():
    return clock.now()


def now_iso():
    return clock.now_iso()


# ---------------------------------------------------------------------------
# Stores (dicts keyed by id)
# ---------------------------------------------------------------------------

districts = {}
technicians = {}
cycles = {}
segments = {}
laterals = {}
inspections = {}
defects = {}
plans = {}
work_orders = {}
line_items = {}
bypass_plans = {}
notices = {}
warranty_cases = {}
flow_periods = {}


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------

def stamp_new(entity):
    """Set created_at/updated_at/version on a freshly-built entity dict."""
    ts = now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and bump version."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 0) + 1
    return entity
