"""In-memory data store. Storage is process-local dicts keyed by id.

The store starts empty on every boot; nothing is seeded. All entities are
constructed exclusively through the declared API surface.
"""
import uuid
from datetime import datetime, timezone

# Startup default for the logical clock (PRD section 2.4).
START_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.referring_providers = {}
        self.specialists = {}
        self.plans = {}
        self.patients = {}
        self.participations = {}
        self.auth_rules = {}
        self.referrals = {}
        self.auth_records = {}
        self.appointments = {}
        self.consult_notes = {}
        self.loop_closures = {}
        self.leakage_records = {}
        self.snapshots = {}
        self.seq = 0
        self.clock = START_CLOCK


store = Store()


def now():
    """Current logical-clock instant (aware, UTC)."""
    return store.clock


def set_clock(dt):
    store.clock = dt


def next_seq():
    store.seq += 1
    return store.seq


def new_id():
    return str(uuid.uuid4())
