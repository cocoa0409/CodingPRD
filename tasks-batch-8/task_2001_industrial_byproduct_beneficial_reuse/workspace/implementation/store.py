"""In-memory data store. Starts empty on every boot — no seeding."""
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.seq = 0
        self.generators = {}
        self.offtakers = {}
        self.streams = {}
        self.characterizations = {}
        self.determinations = {}
        self.permits = {}
        self.agreements = {}
        self.commitments = {}
        self.shipments = {}
        self.facilities = {}
        self.reservations = {}
        self.price_entries = {}
        self.credit_entries = {}
        # shipment_id -> YYYY-MM logical month of latest acceptance (while ACCEPTED)
        self.accepted_periods = {}
        # Logical clock: server default before any call is exactly 2026-08-01T00:00:00Z
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


db = Store()


def next_seq():
    db.seq += 1
    return db.seq
