"""In-memory data store. Everything is wiped on process restart (no persistence)."""
import itertools
import uuid

from clock import Clock


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.parks = {}
        self.lanes = {}
        self.time_blocks = {}
        self.tickets = {}
        self.waivers = {}
        self.season_passes = {}
        self.group_reservations = {}
        self.equipment_rentals = {}
        self.conveyor_turns = {}
        self.add_ons = {}
        self.weather_logs = {}
        self.patrons = {}
        self.refund_entries = {}
        self.clock = Clock()
        # Monotonic sequence to give every record a stable, creation-ordered tiebreaker
        # so list ordering by created_at is deterministic even within the same ms.
        self._seq = itertools.count(1)

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)


def new_store():
    return Store()
