"""In-memory data store. All state lives in module-level dicts keyed by id.
The store starts empty on every boot; nothing is seeded.
"""
import uuid
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_START_TIME = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_logical_now = _START_TIME


def now():
    """Current logical clock time (timezone-aware UTC)."""
    return _logical_now


def set_now(dt):
    global _logical_now
    _logical_now = dt


def iso_now():
    return fmt_dt(now())


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    if dt is None:
        return None
    s = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{s}.{ms:03d}Z"


def parse_dt(value):
    """Parse an ISO-8601 datetime string; returns aware UTC datetime or None."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    v = value.strip()
    try:
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO date (YYYY-MM-DD); returns a datetime.date or None."""
    if value is None or not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def fmt_date(d):
    if d is None:
        return None
    return d.isoformat()


# ---------------------------------------------------------------------------
# Entity stores — plain dicts keyed by id, empty at boot
# ---------------------------------------------------------------------------
programs = {}
employees = {}
lots = {}
permits = {}
renewals = {}
routes = {}
trips = {}
notices = {}
violations = {}
tow_events = {}
billing_cycles = {}
charge_entries = {}
peak_windows = {}


def new_id():
    return str(uuid.uuid4())


def new_record(extra=None):
    """Create base record with common system fields."""
    rec = {
        "id": new_id(),
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "version": 1,
    }
    if extra:
        rec.update(extra)
    return rec


def touch(rec):
    """Refresh updated_at and bump version on a mutated resource."""
    rec["updated_at"] = iso_now()
    rec["version"] = rec.get("version", 1) + 1
