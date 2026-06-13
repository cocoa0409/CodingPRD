"""In-memory data store and server clock.

All state lives in process memory. The store starts EMPTY on every boot —
nothing is seeded, preloaded, or hardcoded. Every entity is created by the
declared API surface at test time.
"""
import datetime
import uuid


def new_id():
    """Server-minted UUID with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


class Clock:
    """Logical server clock. Defaults to real wall-clock UTC; a RaceDirector
    may override it via POST /_clock/set_current_utc (PRD 2.8)."""

    def __init__(self):
        self._override = None  # datetime (aware, UTC) or None

    def set(self, dt):
        self._override = dt

    def now(self):
        if self._override is not None:
            return self._override
        return datetime.datetime.now(datetime.timezone.utc)


class DB:
    """Holds one dict per entity type, keyed by id."""

    def __init__(self):
        self.participants = {}
        self.events = {}
        self.distances = {}
        self.waves = {}
        self.pricing_tiers = {}
        self.registrations = {}
        self.waitlist_entries = {}
        self.fundraising_pledges = {}
        self.transfer_requests = {}
        self.bib_assignments = {}
        self.packet_pickups = {}
        self.result_records = {}
        # Monotonic sequence used purely to break created_at ties deterministically
        # for FIFO / chronological ordering when two rows share an identical
        # timestamp (the logical clock can be pinned to the same instant in tests).
        self._seq = 0
        self.clock = Clock()

    def next_seq(self):
        self._seq += 1
        return self._seq


# Single global instance. Created empty; never seeded.
db = DB()
clock = db.clock
