"""In-memory store and the logical clock. Starts empty on every boot; nothing is seeded."""
import threading
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.regulators = {}
        self.roles = {}
        self.curricula = {}
        self.versions = {}
        self.requirements = {}
        self.employees = {}
        self.role_changes = {}
        self.assignments = {}
        self.completions = {}
        self.campaigns = {}
        self.attestations = {}
        self.exceptions = {}
        self.notices = {}
        self.leaves = {}
        self.reports = {}
        self.clock = DEFAULT_CLOCK
        self.lock = threading.RLock()


store = Store()


def now():
    return store.clock


def new_entity():
    """Common system-managed fields (PRD 2.4): id, created_at, updated_at, version."""
    t = now()
    return {"id": str(uuid.uuid4()), "created_at": t, "updated_at": t, "version": 1}


def touch(e):
    """Any mutation refreshes updated_at and increments version."""
    e["updated_at"] = now()
    e["version"] += 1
