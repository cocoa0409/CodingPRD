"""In-memory data store, logical clock, and id/timestamp helpers.

The store starts EMPTY on every process boot. No entity is seeded, preloaded or
hardcoded — every record is created through the declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

# Recognized roles (PRD 2.1)
ROLES = ("Dispatcher", "Driver", "LabClient", "ComplianceOfficer")

# Startup default of the logical clock (PRD 2.9)
_DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.rate_cards = {}
        self.lab_clients = {}
        self.drivers = {}
        self.vehicles = {}
        self.route_templates = {}
        self.routes = {}
        self.stops = {}
        self.specimens = {}
        self.scan_events = {}
        self.exceptions = {}
        self.billings = {}
        self.clock = _DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


# Single module-level store instance; fresh per process (per-test-server reboot).
db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    """Current logical-clock instant (never wall-clock)."""
    return db.clock


def new_record(fields):
    """Record with the four common system fields (PRD 2.4) plus the given fields."""
    ts = now()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    rec.update(fields)
    return rec


def new_lean_record(fields):
    """ScanEvent record: append-only, carries only id + created_at (PRD 2.4)."""
    rec = {
        "id": new_id(),
        "created_at": now(),
        "_seq": db.next_seq(),
    }
    rec.update(fields)
    return rec


def touch(rec):
    """Register a mutation: refresh updated_at and bump version by one."""
    rec["updated_at"] = now()
    rec["version"] += 1


# ---- datetime parsing / formatting -----------------------------------------

def parse_dt(value):
    """Parse an ISO 8601 string into an aware UTC datetime; None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits and a Z suffix (PRD 2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (dt.microsecond // 1000))
