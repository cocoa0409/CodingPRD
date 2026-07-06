"""In-memory data store. Starts empty on every boot — NO seeding.

All entities are created by the test suite via the declared API surface.
"""
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def iso_ms(dt=None):
    """ISO 8601 UTC timestamp with millisecond precision (PRD §2.4)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.venues = {}
        self.shows = {}
        self.sections = {}
        self.tables = {}
        self.performers = {}
        self.lineup_slots = {}
        self.tiers = {}
        self.reservations = {}
        self.tickets = {}
        self.guest_list_entries = {}
        self.servers = {}
        self.private_events = {}
        self.settlements = {}
        # Monotonic sequence used purely as a stable tiebreak for created_at
        # ordering when two records share the same millisecond timestamp.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
