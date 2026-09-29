"""In-memory data store and logical clock.

The store starts completely EMPTY on every boot.  Nothing is seeded, preloaded
or hardcoded here — every entity is created exclusively by API calls.
"""
import itertools
import threading
import uuid
from datetime import datetime, timezone, timedelta

# PRD 2.4: the logical clock starts at this instant on every boot.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "courses",
    "elements",
    "facilitators",
    "training_records",
    "professional_inspections",
    "operational_logs",
    "group_clients",
    "bookings",
    "participants",
    "program_blocks",
    "block_assignments",
    "belay_equipment",
    "weather_observations",
    "incidents",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)
        self._last_ts = None

    def next_seq(self):
        return next(self._seq)


store = Store()

# Flask's dev server is threaded; every request is serialised behind this lock so
# that the derived-counter recomputations and cascades stay consistent.
request_lock = threading.RLock()


def new_id():
    """PRD 2.9: ids are UUIDs with no type prefix."""
    return str(uuid.uuid4())


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD 2.2/2.9)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_now():
    """Strictly increasing millisecond wall-clock instant.

    Used for created_at / updated_at so that ``created_at`` ascending ordering is
    always identical to insertion order and never ambiguous.
    """
    t = datetime.now(timezone.utc)
    t = t.replace(microsecond=(t.microsecond // 1000) * 1000)
    if store._last_ts is not None and t <= store._last_ts:
        t = store._last_ts + timedelta(milliseconds=1)
    store._last_ts = t
    return t


def wall_now_iso():
    return fmt_instant(wall_now())


def clock_now():
    """Current logical-clock instant."""
    return store.clock


def clock_date():
    """Current logical-clock UTC calendar date."""
    return store.clock.date()


def base_row(common_fields=True):
    row = {
        "id": new_id(),
        "created_at": wall_now_iso(),
        "_seq": store.next_seq(),
    }
    if common_fields:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and bump version — used for direct and cascaded writes."""
    if row is None:
        return
    if "version" in row:
        row["version"] = row["version"] + 1
    if "updated_at" in row:
        row["updated_at"] = wall_now_iso()


def by_created_at(rows):
    """Default ordering: created_at ascending (stable, tie-broken by insertion)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def by_created_at_desc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]), reverse=True)
