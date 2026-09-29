"""In-memory data store. Starts completely empty on every process boot.

No entity is ever seeded, preloaded or hardcoded here; every record is created
through the declared API surface.
"""
import threading
import uuid
from datetime import datetime, timezone

from money import D, q2

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

COLLECTIONS = (
    "zones",
    "varieties",
    "crop_cycles",
    "climate_strategies",
    "fertigation_batches",
    "scouting_observations",
    "bio_control_releases",
    "workers",
    "labor_tasks",
    "harvest_lots",
    "retail_programs",
    "commitment_weeks",
    "lot_allocations",
    "drainage_readings",
)

LOCK = threading.RLock()

db = {name: {} for name in COLLECTIONS}

_state = {
    "clock": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
    "seq": 0,
}


def reset():
    for name in COLLECTIONS:
        db[name] = {}
    _state["clock"] = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
    _state["seq"] = 0


def now():
    """The server-held logical clock. Never falls back to host wall-clock time."""
    return _state["clock"]


def set_clock(dt):
    _state["clock"] = dt


def next_seq():
    _state["seq"] += 1
    return _state["seq"]


def new_id():
    return str(uuid.uuid4())


def iso3(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def midnight(day):
    """The 00:00:00Z instant opening a calendar date."""
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def base_record(with_common=True):
    rec = {"id": new_id(), "created_at": now()}
    if with_common:
        rec["updated_at"] = now()
        rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """Register a mutation: fresh updated_at plus a version increment."""
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 1) + 1


def ordered(collection, predicate=None):
    """Default list order: created_at ascending, insertion order as the tiebreak."""
    rows = [r for r in db[collection].values() if predicate is None or predicate(r)]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def sum_dec(values):
    total = D(0)
    for v in values:
        total += v
    return total


def q2sum(values):
    return q2(sum_dec(values))
