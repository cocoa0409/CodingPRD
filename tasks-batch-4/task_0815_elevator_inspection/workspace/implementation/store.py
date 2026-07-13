"""In-memory data store and the logical clock.

Everything lives in module-level dicts keyed by id. Nothing is persisted to
disk; a fresh process starts completely empty (no seeded entities). The logical
clock defaults to period index 0 at startup.
"""

import itertools
import uuid
from datetime import datetime, timezone


class DB:
    def __init__(self):
        self.reset()

    def reset(self):
        self.owners = {}
        self.inspectors = {}
        self.devices = {}
        self.inspections = {}
        self.deficiencies = {}
        self.citations = {}
        self.certificates = {}
        self.oos_orders = {}
        self.fee_invoices = {}
        self.accident_reports = {}
        self.current_period_index = 0
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


db = DB()


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def base_fields():
    """Common system fields shared by every persisted entity."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(entity):
    """Record a mutation: bump version and refresh updated_at."""
    entity["version"] += 1
    entity["updated_at"] = now_iso()
