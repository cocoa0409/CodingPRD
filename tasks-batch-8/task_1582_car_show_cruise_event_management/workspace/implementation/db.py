"""In-memory data store. Store starts EMPTY on every boot - no seeding."""
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Real wall-clock timestamp for created_at/updated_at (ISO 8601, 3 fractional digits, Z)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


class Store:
    def __init__(self):
        self.events = {}
        self.classes = {}
        self.zones = {}
        self.registrants = {}
        self.vehicles = {}
        self.registrations = {}
        self.payments = {}
        self.waivers = {}
        self.booth_applications = {}
        self.judges = {}
        self.score_sheets = {}
        self.ballots = {}
        self.awards = {}
        self.noise_readings = {}
        self.sound_slots = {}
        # insertion-order counters for created_at-ascending sorts (stable)
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


STORE = Store()


# ----------------------------------------------------------------------------
# Logical clock (module-level so every import shares it)
# ----------------------------------------------------------------------------
class LogicalClock:
    def __init__(self):
        self.current = '2026-08-01T00:00:00Z'

    def now(self):
        return self.current

    def set(self, iso):
        self.current = iso


CLOCK = LogicalClock()
