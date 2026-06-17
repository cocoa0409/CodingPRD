"""In-memory data store. Starts EMPTY on every boot — no seeding."""
import uuid
from datetime import datetime, timezone

from response import now_iso


class DB:
    def __init__(self):
        self.brokerages = {}
        self.brokers = {}
        self.properties = {}
        self.spaces = {}
        self.listings = {}
        self.requirements = {}
        self.tours = {}
        self.deals = {}
        self.proposals = {}
        self.commission_splits = {}
        self.comps = {}
        # Monotonic insertion sequence to keep created_at ordering stable
        # even when multiple records share the same millisecond timestamp.
        self._seq = 0
        # Test-driving server clock (overridable via /_clock/set_current_utc).
        self._clock = None

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())

    def set_clock(self, dt):
        self._clock = dt

    def current_clock(self):
        if self._clock is not None:
            return self._clock
        return datetime.now(timezone.utc)

    def current_clock_iso(self):
        dt = self.current_clock().astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


db = DB()


def new_full_record(extra_fields):
    """Full mutable record: id, created_at, updated_at, version (PRD §2.4)."""
    ts = now_iso()
    rec = {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    rec["_seq"] = db.next_seq()
    rec.update(extra_fields)
    return rec


def new_lean_record(extra_fields):
    """Lean record (CommissionSplit, Comp): id + created_at only (PRD §2.4)."""
    rec = {
        "id": db.new_id(),
        "created_at": now_iso(),
    }
    rec["_seq"] = db.next_seq()
    rec.update(extra_fields)
    return rec


def touch(rec):
    """Mutate a full record: bump updated_at and version (PRD §2.4)."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
