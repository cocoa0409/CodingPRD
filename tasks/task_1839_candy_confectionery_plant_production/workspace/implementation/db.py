"""In-memory data store and the plant logical clock.

Storage is in-memory only (Python dicts keyed by id). The store starts empty
on every boot; no entity is ever seeded at startup. Every time-dependent rule
reads the server-side logical clock, never the host wall clock.
"""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.products = {}
        self.recipes = {}
        self.gift_components = {}
        self.packaging_components = {}
        self.purchase_orders = {}
        self.molds = {}
        self.production_lines = {}
        self.changeovers = {}
        self.seasonal_windows = {}
        self.production_runs = {}
        self.lots = {}
        self.quality_holds = {}


store = Store()

# ---------------------------------------------------------------------------
# Logical clock. Startup default is exactly 2026-08-01T00:00:00Z and it never
# falls back to wall-clock time.
# ---------------------------------------------------------------------------
_STARTUP_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"current": _STARTUP_CLOCK}


def now():
    return _clock["current"]


def set_now(dt):
    _clock["current"] = dt


def iso(dt):
    """Serialize a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 datetime string to an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def stamp_new(entity):
    """Set the system-managed common fields on a freshly created resource."""
    entity["created_at"] = now()
    entity["updated_at"] = now()
    entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and increment version on any mutation (client action
    or internal cascade alike)."""
    entity["updated_at"] = now()
    entity["version"] += 1
