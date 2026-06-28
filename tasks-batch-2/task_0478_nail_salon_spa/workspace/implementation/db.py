"""In-memory data store. Wiped on every process boot (no persistence).

The store starts EMPTY on every boot. No entity is ever seeded, preloaded, or
hardcoded at startup; every entity is created by the test via the API surface.
"""
import itertools
import uuid

# Monotonic sequence so we can break created_at ties deterministically
# (list sorts and statement sweeps rely on stable ordering, never on id).
_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        # one dict per entity type, keyed by id
        self.technicians = {}
        self.stations = {}
        self.sanitation_logs = {}
        self.menu_items = {}
        self.add_ons = {}
        self.clients = {}
        self.appointments = {}
        self.appointment_add_ons = {}
        self.gift_cards = {}
        self.commission_statements = {}

    def next_seq(self):
        return next(_seq)


db = Store()
