"""In-memory data store. Starts EMPTY on every boot — no seeding.

Each entity type lives in its own dict keyed by UUID id. Resources carry the
common fields per PRD §2.4: id (UUID, no prefix), created_at, updated_at
(ISO 8601 UTC, 3 fractional digits), and an integer version (begins at 1,
+1 on every mutation). created_at doubles as the deterministic ordering key,
tie-broken by a monotonic creation sequence (PRD §2.3 / §2.4).
"""

import itertools
import threading
import uuid
from datetime import datetime, timezone

# Monotonic creation counter so created_at ties break deterministically when
# sorting list results by creation order (PRD §2.3 / §2.4).
_seq = itertools.count(1)
_lock = threading.RLock()


def new_id():
    return str(uuid.uuid4())


def wall_now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


class Store:
    def __init__(self):
        self.patients = {}
        self.referrals = {}
        self.beds = {}
        self.study_orders = {}
        self.scoring_reports = {}
        self.dme_orders = {}
        self.compliance_records = {}
        self.follow_ups = {}

    def stamp_new(self, record):
        """Attach common fields to a freshly created record."""
        ts = wall_now_iso()
        record["id"] = record.get("id") or new_id()
        record["created_at"] = ts
        record["updated_at"] = ts
        record["version"] = 1
        record["_seq"] = next(_seq)
        return record

    def touch(self, record):
        """Register a mutation: bump version, refresh updated_at (PRD §2.4)."""
        record["version"] = record.get("version", 1) + 1
        record["updated_at"] = wall_now_iso()
        return record


db = Store()
lock = _lock
