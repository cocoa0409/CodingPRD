"""In-memory data store and logical clock.

All state lives in module-level dicts keyed by id. The store starts empty on
every process launch; nothing is ever seeded or preloaded. `start.sh`
re-invocation (per-test-server isolation) therefore wipes all state.
"""
import itertools
import uuid
from datetime import datetime, timezone

# The logical clock reads exactly this instant on startup (PRD 2.5). It never
# advances on its own and never falls back to wall-clock time.
CLOCK_DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.operators = {}
        self.vehicles = {}
        self.permits = {}
        self.staging_lots = {}
        self.queue_entries = {}
        self.curb_zones = {}
        self.curb_assignments = {}
        self.trips = {}
        self.violations = {}
        self.settlements = {}
        self.clock = CLOCK_DEFAULT
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    return db.clock


def base_record():
    """Common fields shared by every persisted resource (PRD 2.4)."""
    ts = db.clock
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(rec):
    """Any mutation refreshes updated_at to the current logical clock and
    increments version by one (PRD 2.4)."""
    rec["updated_at"] = db.clock
    rec["version"] += 1
