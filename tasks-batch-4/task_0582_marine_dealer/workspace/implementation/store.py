"""In-memory data store, logical clock, and id/timestamp helpers.

The store starts EMPTY on every process boot. No entity is seeded or preloaded.
"""
import itertools
import uuid
from datetime import datetime, timezone

# Recognized roles (PRD 2.1)
ROLES = {"Manager", "SalesRep", "ServiceAdvisor", "PartsClerk"}

# Constants (SCAFFOLD 1.3 / PRD)
MIN_DOWN_BPS = 1000
DAYS_PER_YEAR = 365
PAYOFF_NOTICE_DAYS = 10
CURTAILMENT_DUE_DAYS = 90
BAY_BUFFER_MINUTES = 30

# Default logical clock at startup (PRD 2.6)
_DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.units = {}
        self.floor_plans = {}
        self.deals = {}
        self.consignments = {}
        self.repair_orders = {}
        self.service_lines = {}
        self.parts = {}
        self.berths = {}
        self.service_bays = {}
        self.slip_reservations = {}
        self.clock = _DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


# Single module-level store instance. Fresh per process (per-test-server reboot).
db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    """Current logical-clock instant."""
    return db.clock


def new_record(extra_fields):
    """Create a record dict with the four common system fields plus given fields."""
    ts = now()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    rec.update(extra_fields)
    return rec


def touch(rec):
    """Register a mutation: refresh updated_at and bump version."""
    rec["updated_at"] = now()
    rec["version"] += 1


# ---- datetime parsing / formatting -----------------------------------------

def parse_dt(value):
    """Parse an ISO 8601 string into an aware UTC datetime. Returns None on failure."""
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
    """Format an aware datetime as ISO 8601 UTC with three fractional digits + Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (dt.microsecond // 1000))
