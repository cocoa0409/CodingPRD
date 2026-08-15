"""In-memory data store and logical clock. The store starts EMPTY on every
boot — no seeding of any kind."""
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = 0
        # Logical clock: server-startup default, never wall-clock.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.programs = {}
        self.participants = {}
        self.contacts = {}
        self.waitlist = {}
        self.volunteers = {}
        self.windows = {}
        self.training = {}
        self.agreements = {}
        self.schedules = {}
        self.assignments = {}
        self.logs = {}
        self.escalations = {}
        self.welfare = {}
        self.referrals = {}
        self.surveys = {}
        self.reports = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def now():
    return store.clock


def new_entity():
    ts = now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(e):
    e["updated_at"] = now()
    e["version"] += 1
