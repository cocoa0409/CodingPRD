"""In-memory data store + logical clock. Empty at boot; tests build all state via the API."""
import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4): starts at exactly 2026-08-01T00:00:00Z, never wall-clock.
# ---------------------------------------------------------------------------

_INITIAL_CLOCK_ISO = "2026-08-01T00:00:00Z"


def parse_iso(value):
    """Parse ISO 8601 datetime. Accepts trailing 'Z' and fractional seconds."""
    if value is None:
        return None
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


def format_iso(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits + 'Z'."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}" + "Z"


class _Clock:
    def __init__(self):
        self._now = parse_iso(_INITIAL_CLOCK_ISO)

    def now(self):
        return self._now

    def now_iso(self):
        return format_iso(self._now)

    def set(self, value):
        self._now = parse_iso(value)


clock = _Clock()


def new_id():
    return str(uuid.uuid4())


def now_dt():
    return clock.now()


def now_iso():
    return clock.now_iso()


# ---------------------------------------------------------------------------
# Stores (dicts keyed by id) — one per entity, all empty at boot
# ---------------------------------------------------------------------------

facilities = {}
rate_schedules = {}
access_devices = {}
parker_accounts = {}
monthly_agreements = {}
credentials = {}
parking_sessions = {}
shifts = {}
reconciliations = {}
inspections = {}
repair_projects = {}
maintenance_windows = {}
patrol_rounds = {}
incidents = {}
ev_chargers = {}
charging_sessions = {}
event_bookings = {}


_seq_counter = [0]


def stamp_new(entity):
    """Set created_at/updated_at/version on a freshly-built entity dict."""
    ts = now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    _seq_counter[0] += 1
    entity["_seq"] = _seq_counter[0]
    return entity


def touch(entity):
    """Refresh updated_at and bump version (PRD 2.5: every mutation)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 0) + 1
    return entity


def touch_ledger(entity):
    """Facility ledger write: refresh updated_at but do NOT bump version.

    PRD 2.5/2.7: Facility.version advances only where section 3 states it
    (publish, manual posture transition, CRITICAL report, repair start/close-out,
    event activation surge, close-of-business). Ledger-only writes
    (cumulative_collected, deposit_liability, capital_reserve) do not advance it.
    """
    entity["updated_at"] = now_iso()
    return entity
