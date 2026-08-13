"""In-memory data store. The store starts completely empty on every boot;
no entity is ever seeded. Also owns the logical clock (default
2026-08-01T00:00:00Z, never falls back to wall-clock time)."""
import uuid
from datetime import datetime, timezone

UTC = timezone.utc
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Store:
    def __init__(self):
        self.classes = {}
        self.equipment = {}
        self.projects = {}
        self.assignments = {}
        self.charges = {}
        self.work_orders = {}
        self.mechanics = {}
        self.transport_jobs = {}
        self.lowboys = {}
        self.readings = {}
        self.damage_reports = {}
        self.clock = DEFAULT_CLOCK
        self.seq = 0


store = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    return store.clock


def next_seq():
    store.seq += 1
    return store.seq


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_clock(dt):
    """Clock echo format: no fraction when zero, else three digits."""
    dt = dt.astimezone(UTC)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_ts(dt)


def new_common():
    ts = fmt_ts(store.clock)
    return {"id": new_id(), "created_at": ts, "updated_at": ts,
            "version": 1, "_seq": next_seq()}


def new_sub():
    """AssignmentCharge / TelematicsReading: only id + created_at."""
    return {"id": new_id(), "created_at": fmt_ts(store.clock), "_seq": next_seq()}


def touch(ent):
    """A mutation of the resource: version += 1, updated_at refreshed."""
    ent["version"] += 1
    ent["updated_at"] = fmt_ts(store.clock)


def pub(d):
    """Public view: strip internal underscore keys."""
    return {k: v for k, v in d.items() if not k.startswith("_")}


def pub_equipment(e):
    out = pub(e)
    out["hours_since_service_milli"] = e["engine_hours_milli"] - e["hours_at_last_service_milli"]
    return out
