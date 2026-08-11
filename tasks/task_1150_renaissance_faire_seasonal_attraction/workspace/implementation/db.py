"""In-memory data store and logical clock.

The store starts empty on every boot. No seeding, no persistence.
"""
import uuid
from datetime import datetime, timezone

# Startup default of the logical clock per PRD section 2.5.
CLOCK_STARTUP_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.seasons = {}
        self.faire_days = {}
        self.performers = {}
        self.contracts = {}
        self.slots = {}
        self.vendors = {}
        self.applications = {}
        self.booths = {}
        self.permits = {}
        self.orders = {}
        self.tickets = {}
        self.rain_checks = {}
        self.shifts = {}
        self.cases = {}
        self.tasks = {}
        self.seq = 0
        self.clock = CLOCK_STARTUP_DEFAULT


store = Store()


def new_id():
    """Server-minted UUID, no type prefix."""
    return str(uuid.uuid4())


def next_seq():
    store.seq += 1
    return store.seq


def clock_now():
    return store.clock


def set_clock(dt):
    store.clock = dt
