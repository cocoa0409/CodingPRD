"""In-memory data store + logical clock. No persistence, no seeding."""
import itertools
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # Logical clock: starts exactly at 2026-08-01T00:00:00Z, never wall-clock.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = itertools.count(1)
        self.dealers = {}
        self.series = {}
        self.glass_packages = {}
        self.energy_rules = {}
        self.orders = {}
        self.lines = {}
        self.labels = {}
        self.ig_units = {}
        self.waves = {}
        self.racks = {}
        self.reservations = {}
        self.claims = {}
        self.shipments = {}


STORE = Store()


def current_time():
    return STORE.clock


def set_clock(dt):
    STORE.clock = dt


def next_seq():
    return next(STORE.seq)


def new_id():
    return str(uuid.uuid4())


def new_entity(fields):
    now = current_time()
    e = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    e.update(fields)
    return e


def touch(e):
    e["updated_at"] = current_time()
    e["version"] += 1
