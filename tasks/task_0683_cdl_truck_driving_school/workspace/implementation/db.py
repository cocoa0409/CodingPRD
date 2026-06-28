"""In-memory data store. Starts EMPTY on every boot — no seeding/preload.

Each entity type is a dict keyed by id. A monotonically increasing insertion
sequence is recorded per record so list endpoints can sort by created_at
ascending deterministically (PRD §2.3) even when timestamps collide.
"""
from clock import clock
from util import new_id, iso_now


class Store:
    def __init__(self):
        self.programs = {}
        self.trucks = {}
        self.instructors = {}
        self.enrollments = {}
        self.prereq_documents = {}
        self.clock_sessions = {}
        self.skills_tests = {}
        self.carriers = {}
        self.sponsorship_offers = {}
        self.finance_plans = {}
        self.completion_reports = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def stamp_create(record):
    """Set system common fields on a freshly created record (PRD §2.4)."""
    now = iso_now(clock.now())
    record["id"] = new_id()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Refresh updated_at and increment version on mutation (PRD §2.4/§2.6)."""
    record["updated_at"] = iso_now(clock.now())
    record["version"] = record.get("version", 1) + 1
    return record
