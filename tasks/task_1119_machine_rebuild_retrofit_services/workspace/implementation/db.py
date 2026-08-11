"""In-memory data store and logical clock.

Storage is in-memory only (Python dicts). Every start.sh re-launch boots a
fresh, empty store. No seeding anywhere: tests construct all state via the API.
"""

import itertools
import uuid
from datetime import datetime, timezone

from util import iso3


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.7). Starts at exactly 2026-05-01T00:00:00Z and never
# falls back to wall-clock time.
# ---------------------------------------------------------------------------
class LogicalClock:
    INITIAL_RAW = "2026-05-01T00:00:00Z"

    def __init__(self):
        self.now = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.raw = self.INITIAL_RAW  # verbatim string, echoed in current_utc

    def set(self, dt, raw):
        self.now = dt
        self.raw = raw

    def iso(self):
        return iso3(self.now)


clock = LogicalClock()


class Store:
    def __init__(self):
        self.customers = {}
        self.machines = {}
        self.assessments = {}
        self.projects = {}
        self.parts = {}
        self.part_lines = {}
        self.re_jobs = {}
        self.windows = {}
        self.stages = {}
        self.tests = {}
        self.training_records = {}
        self.claims = {}
        self.offers = {}
        self._seq = itertools.count(1)


store = Store()


def new_record(fields):
    """Create a record dict with system-managed common fields (PRD §2.4)."""
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    ts = clock.iso()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next(store._seq)
    rec["_created_dt"] = clock.now
    return rec


def bump(rec):
    """Apply a mutation: refresh updated_at and increment version (PRD §2.4)."""
    rec["updated_at"] = clock.iso()
    rec["version"] += 1


def sorted_records(mapping):
    """All records in ascending creation order (PRD §2.3 default sort)."""
    return sorted(mapping.values(), key=lambda r: r["_seq"])


def strip_internal(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}
