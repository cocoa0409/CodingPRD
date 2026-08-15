from datetime import datetime, timezone

# Logical clock startup default: exactly 2026-08-01T00:00:00Z, never wall-clock.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    """In-memory storage only. A fresh Store (empty dicts, default clock) is
    created at every process boot; start.sh re-invocation wipes all state."""

    def __init__(self):
        self.projects = {}
        self.plans = {}
        self.workers = {}
        self.certificates = {}
        self.subcontractors = {}
        self.huddles = {}
        self.jhas = {}
        self.inspections = {}
        self.deficiencies = {}
        self.incidents = {}
        self.permits = {}
        self.drugtests = {}
        self.clock = CLOCK_DEFAULT
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def now():
    """Current logical time (second precision)."""
    return store.clock
