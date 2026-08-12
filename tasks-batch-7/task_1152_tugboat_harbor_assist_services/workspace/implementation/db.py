"""In-memory data store. Starts completely empty on every boot — no seeding."""
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = 0
        # Logical clock default: exactly 2026-05-01T00:00:00Z (PRD §2.4).
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.vessels = {}
        self.tugs = {}
        self.pilots = {}
        self.crew_members = {}
        self.tariff_rates = {}
        self.job_orders = {}
        self.tug_assignments = {}
        self.pilot_bookings = {}
        self.watch_rotations = {}
        self.gear_inspections = {}
        self.incidents = {}
        self.weather_restrictions = {}
        self.invoices = {}
        self.damage_claims = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def now():
    return store.clock


def new_id():
    import uuid
    return str(uuid.uuid4())


def stamp_new(rec):
    """Set id/created_at/updated_at/version on a freshly built record."""
    t = now()
    rec['created_at'] = t
    rec['updated_at'] = t
    rec['version'] = 1
    rec['_seq'] = store.next_seq()
    return rec


def stamp_new_immutable(rec):
    """GearInspection: only id and created_at (PRD §2.5)."""
    rec['created_at'] = now()
    rec['_seq'] = store.next_seq()
    return rec


def touch(rec):
    """Mutation stamp: refresh updated_at and increment version (PRD §2.5)."""
    rec['updated_at'] = now()
    rec['version'] += 1
