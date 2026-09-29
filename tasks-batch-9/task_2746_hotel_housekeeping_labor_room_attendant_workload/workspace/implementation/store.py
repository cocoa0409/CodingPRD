"""In-memory data store and the logical UTC clock.

Storage is process-local Python dicts only: no database, no file, no cache.  The
store is EMPTY on every boot -- nothing is seeded, preloaded or hardcoded.  Every
entity a caller needs is built through the declared API surface.

PRD 2.4: time in this system is not wall-clock time.  The server keeps a logical
UTC clock which reads exactly 2026-08-01T00:00:00Z before any call to
POST /_clock/set_current_utc, and it must never fall back on real wall-clock time.
"""

import random
import string
import uuid
from datetime import datetime, timezone

from timeutil import format_iso_datetime


LOGICAL_CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "properties",
    "room_types",
    "rooms",
    "attendants",
    "forecast_days",
    "rosters",
    "assignments",
    "inspections",
    "linen_items",
    "laundry_cycles",
    "lost_found_items",
    "enrollments",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = LOGICAL_CLOCK_EPOCH
        self._seq = 0

    # ---- identity and ordering ------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        """The logical clock instant."""
        return self.clock

    def set_clock(self, dt):
        self.clock = dt


STORE = Store()


def new_id():
    """Server-minted UUID string with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def base_record(store, with_version=True):
    """The common resource properties every minted resource carries."""
    now = store.now()
    rec = {
        "id": new_id(),
        "_seq": store.next_seq(),
        "created_at": now,
    }
    if with_version:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(store, record):
    """Refresh updated_at and increment version -- PRD 2.4/2.9: recomputation of a
    derived field counts as a mutation of the resource it lands on."""
    if "version" in record:
        record["updated_at"] = store.now()
        record["version"] = record["version"] + 1
    return record


def common_out(record):
    out = {"id": record["id"], "created_at": format_iso_datetime(record["created_at"])}
    if "version" in record:
        out["updated_at"] = format_iso_datetime(record["updated_at"])
        out["version"] = record["version"]
    return out


def sorted_rows(rows):
    """PRD 2.3: list endpoints return resources sorted by created_at ascending.
    The insertion sequence keeps that ordering total when the logical clock has
    not advanced between two creations."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
