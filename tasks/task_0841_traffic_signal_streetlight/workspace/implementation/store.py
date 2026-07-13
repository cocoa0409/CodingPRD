"""In-memory data store, logical clock, and time / id helpers.

Storage is process-local Python dicts only; a fresh process starts completely
empty (no seeding, no persistence).
"""
import random
import string
import uuid
from datetime import datetime, timezone, timedelta

UTC = timezone.utc

# Startup default for the logical clock (never falls back to wall-clock time).
CLOCK_DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)


def parse_dt(value):
    """Parse an ISO-8601 string into an aware UTC datetime, or return None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        if not isinstance(value, str):
            raise ValueError("not a datetime string")
        s = value.strip()
        if s.endswith("Z") or s.endswith("z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fmt_dt(dt):
    """Format an aware datetime as ISO-8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def now_real():
    """Real wall-clock UTC — used for created_at / updated_at / request stamps."""
    return datetime.now(UTC)


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


class Store:
    def __init__(self):
        self.clock = CLOCK_DEFAULT
        self._seq = 0
        self.intersections = {}
        self.poles = {}
        self.devices = {}
        self.pole_attachments = {}
        self.crews = {}
        self.tickets = {}
        self.work_orders = {}
        self.tcrs = {}
        self.locate_requests = {}
        self.warranty_claims = {}

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_entity(self):
        return {
            "id": new_id(),
            "created_at": now_real(),
            "updated_at": now_real(),
            "version": 1,
            "_seq": self.next_seq(),
        }

    def touch(self, entity):
        entity["updated_at"] = now_real()
        entity["version"] += 1


# Single global store instance (rebuilt fresh on every process start).
store = Store()


# ---------------------------------------------------------------------------
# Computed / derived helpers
# ---------------------------------------------------------------------------
def intersection_posture(intersection_id):
    devs = [
        d for d in store.devices.values()
        if d["intersection_id"] == intersection_id and d["status"] != "DECOMMISSIONED"
    ]
    if any(d["status"] == "KNOCKED_DOWN" for d in devs):
        return "EMERGENCY"
    if any(d["status"] in ("OUT_OF_SERVICE", "UNDER_MAINTENANCE") for d in devs):
        return "DEGRADED"
    return "NORMAL"


def pole_committed_load(pole_id):
    return sum(
        a["load_units"] for a in store.pole_attachments.values()
        if a["pole_id"] == pole_id and a["status"] == "APPROVED"
    )


def crew_committed_hours(crew_id):
    return sum(
        w["estimated_labor_hours"] for w in store.work_orders.values()
        if w.get("crew_id") == crew_id and w["status"] in ("SCHEDULED", "DISPATCHED")
    )
