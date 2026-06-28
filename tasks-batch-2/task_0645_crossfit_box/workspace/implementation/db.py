"""In-memory data store (PRD §2.4 common resource properties).

Every primary resource carries id (UUID, no prefix), created_at, updated_at
(ISO 8601 UTC, three fractional digits), and version (integer, starts at 1,
increments by one on every mutation).

The store starts EMPTY on every boot. No entity is seeded, preloaded, or
hardcoded at startup; every entity is constructed by tests via the API surface.
"""
import itertools
import uuid

from clock import clock
from response import iso_ms


class DB:
    def __init__(self):
        self.reset()

    def reset(self):
        self.membership_plans = {}
        self.members = {}
        self.memberships = {}
        self.program_tracks = {}
        self.coaches = {}
        self.sessions = {}
        self.reservations = {}
        self.benchmark_results = {}
        self.teams = {}
        self.team_members = {}
        # Monotonic sequence used as a stable secondary sort key so that
        # "creation order" is deterministic even within the same logical-clock
        # instant (created_at can tie when the clock is fixed).
        self._seq = itertools.count(1)

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)

    def stamp_create(self, obj):
        now = iso_ms(clock.now())
        obj.setdefault("id", self.new_id())
        obj["created_at"] = now
        obj["updated_at"] = now
        obj["version"] = 1
        obj["_seq"] = self.next_seq()
        return obj

    def touch(self, obj):
        """Refresh updated_at and increment version (a mutation)."""
        obj["updated_at"] = iso_ms(clock.now())
        obj["version"] = obj.get("version", 1) + 1
        return obj


db = DB()
