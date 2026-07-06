"""In-memory data store. NO seeding — every collection starts empty on boot.

Tests build all state via the declared API surface. The store is a singleton
constructed at import time; the process restarts before every per-test run, so
state is wiped each time.
"""
import uuid

from clock import LogicalClock, iso


class Store:
    def __init__(self):
        # Each collection: id -> dict record.
        self.skill_tags = {}
        self.sla_policies = {}
        self.clients = {}
        self.virtual_assistants = {}
        self.engagements = {}
        self.retainer_cycles = {}
        self.tasks = {}
        self.time_entries = {}
        self.addons = {}
        self.escalations = {}
        self.invoices = {}
        self.clock = LogicalClock()
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())

    def clock_iso(self):
        """Three-fractional-digit clock string, for created_at/updated_at."""
        return self.clock.iso()

    def clock_iso_logical(self):
        """Second-precision clock string, for clock-derived *_iso stamps."""
        return self.clock.iso_clock()


db = Store()


# --- common system fields ---------------------------------------------------
# Full-lifecycle entities carry id, created_at, updated_at, version (PRD §2.4).
# Reference records (SkillTag, SlaPolicy, Clock) carry only id + created_at.

def stamp_create(record, full_lifecycle=True):
    record["id"] = db.new_id()
    record["created_at"] = db.clock_iso()
    # Hidden monotonic insertion sequence. created_at is the logical-clock
    # value (§2.5) and can repeat when the clock is not advanced between
    # creates; _seq gives a deterministic "earlier registered" total order for
    # list sorting (§2.3 created_at ASC) and the VA match created_at tie-break
    # (§3.3 — earlier-registered VA wins; id never consulted).
    record["_seq"] = db.next_seq()
    if full_lifecycle:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at + bump version on any mutation (§2.4 / §2.10)."""
    record["updated_at"] = db.clock_iso()
    record["version"] = record.get("version", 1) + 1
