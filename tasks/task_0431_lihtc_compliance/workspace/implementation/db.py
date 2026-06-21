"""In-memory data store. Starts empty on every boot — no seeding."""

import threading
import uuid
from datetime import datetime, timezone


def _now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


class DB:
    """Holds one dict per entity collection, keyed by id. Append-order preserved."""

    def __init__(self):
        self.lock = threading.RLock()
        self.projects = {}
        self.buildings = {}
        self.units = {}
        self.households = {}
        self.certifications = {}
        self.leases = {}
        self.inspections = {}
        self.findings = {}
        self.form8609s = {}
        # monotonically increasing sequence to break creation-order ties
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def stamp_create(record):
    """Set common fields on a freshly created record (§2.5)."""
    ts = _now_iso()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Mark a record as mutated: bump updated_at and version (§2.5)."""
    record["updated_at"] = _now_iso()
    record["version"] = record.get("version", 1) + 1
    return record
