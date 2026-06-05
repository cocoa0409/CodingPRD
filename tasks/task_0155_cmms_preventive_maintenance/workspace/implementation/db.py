"""In-memory data store for the CMMS Preventive Maintenance API.

All state lives in module-level dicts keyed by id. The store starts EMPTY on
every process boot — nothing is seeded, preloaded, or hardcoded. Each
`start.sh` re-invocation re-imports this module fresh, wiping all state.

System/common fields (PRD §2.4):
  - id: server-minted UUID, no type prefix
  - created_at: ISO 8601 UTC, 3 fractional digits, set at create
  - updated_at: ISO 8601 UTC, refreshed on every mutation
  - version: integer starting at 1, +1 on every mutation
A MeterReading is the lone exception: only id + created_at (PRD §2.4).
"""
import itertools
import threading
import uuid
from datetime import datetime, timezone

# A global re-entrant lock to keep multi-step mutations atomic under the Flask
# threaded server.
LOCK = threading.RLock()

# One dict per entity collection, keyed by id.
sites = {}
spare_parts = {}
technicians = {}
assets = {}
pm_schedules = {}
meter_readings = {}
work_orders = {}
part_reservations = {}
downtime_events = {}
warranty_claims = {}

# Monotonic creation sequence so list ordering by created_at is stable even when
# two records share the same millisecond timestamp.
_seq = itertools.count(1)

# ---------------------------------------------------------------------------
# Test-driving logical clock (PRD §2.9).
#
# A MaintenanceManager may set the server's current UTC instant. Every domain
# reference to "now" — calendar PM due-checks, warranty coverage windows, and
# the timestamps written into opened_at, closed_at, and resolved downtime —
# uses this value until it is set again. When never set, it tracks the real
# wall clock.
#
# System/envelope fields (api_request_timestamp, created_at, updated_at) are
# distinct system-managed timestamps per PRD §2.2/§2.4 and use the real wall
# clock regardless of the logical clock.
# ---------------------------------------------------------------------------
_clock_override = None  # datetime (UTC) or None


def _real_now():
    return datetime.now(timezone.utc)


def set_clock(dt):
    """Set the logical clock to the given timezone-aware UTC datetime."""
    global _clock_override
    _clock_override = dt


def logical_now():
    """Return the current logical 'now' as a timezone-aware UTC datetime."""
    if _clock_override is not None:
        return _clock_override
    return _real_now()


def logical_now_iso():
    return iso(logical_now())


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    """Real wall-clock ISO timestamp for system/common fields."""
    return iso(_real_now())


def parse_stored_dt(value):
    """Parse a stored ISO 8601 string back into a timezone-aware UTC datetime.

    Stored datetimes are always written via iso() (trailing 'Z'), so this is a
    straightforward reverse. Returns None for None.
    """
    if value is None:
        return None
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def next_seq():
    return next(_seq)


def new_record(with_version=True):
    """Build a fresh record with the system-managed common fields (PRD §2.4)."""
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "_seq": next_seq(),
    }
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Mark a record as mutated: refresh updated_at and bump version by one.

    PRD §2.4: recomputation of a derived field counts as a mutation of the
    resource that owns it, so callers invoke touch() on every reconciliation.
    """
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


def reset():
    """Clear all collections and the clock override. Used only for safety in
    case the module is re-imported within a single process; a fresh process
    already starts empty."""
    global _clock_override
    sites.clear()
    spare_parts.clear()
    technicians.clear()
    assets.clear()
    pm_schedules.clear()
    meter_readings.clear()
    work_orders.clear()
    part_reservations.clear()
    downtime_events.clear()
    warranty_claims.clear()
    _clock_override = None
