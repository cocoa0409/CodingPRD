"""In-memory data store, logical clock and id / timestamp helpers.

Storage is process-local and starts completely empty on every boot.  Nothing is
seeded, preloaded or hardcoded: every entity is created through the declared API
surface.
"""
import itertools
import threading
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.5: the logical clock starts at this fixed instant and never falls back
# to wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def wall_now():
    return datetime.now(timezone.utc)


class Store(object):
    def __init__(self):
        self.business_units = {}
        self.tagging_policies = {}
        self.provisioning_requests = {}
        self.cloud_resources = {}
        self.cost_records = {}
        self.shared_cost_pools = {}
        self.allocation_runs = {}
        self.allocation_lines = {}
        self.chargeback_invoices = {}
        self.disputes = {}
        self.commitments = {}
        self.remediation_tasks = {}
        self.anomaly_alerts = {}
        self.budgets = {}
        self.unit_economics_drivers = {}
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)
        self.lock = threading.RLock()

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    """Current logical clock instant."""
    return db.clock


def base_fields(with_version=True):
    """Common system-managed properties (PRD 2.4)."""
    stamp = fmt_dt(wall_now())
    rec = {"id": new_id(), "created_at": stamp}
    if with_version:
        rec["updated_at"] = stamp
        rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(entity):
    """Record a mutation: refresh updated_at and increment version."""
    if "version" in entity:
        entity["updated_at"] = fmt_dt(wall_now())
        entity["version"] = entity["version"] + 1


def sort_key(entity):
    return (entity.get("created_at", ""), entity.get("_seq", 0))


def ordered(values):
    return sorted(values, key=sort_key)


def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)
