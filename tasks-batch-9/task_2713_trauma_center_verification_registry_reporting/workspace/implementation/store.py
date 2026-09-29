"""In-memory data store, id generation and the logical clock.

Storage is process-local and starts completely empty on every boot: no seeding,
no preloading, no persistence to disk.
"""
import datetime
import itertools
import uuid

# PRD 2.4: on startup the logical clock reads exactly 2026-08-01T00:00:00Z and
# never falls back to real wall-clock time.
CLOCK_DEFAULT = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)

# Collections that carry version/updated_at (DataDictionaryRule is immutable and
# therefore excluded from the mutation bookkeeping).
VERSIONED_COLLECTIONS = [
    "centers",
    "tiers",
    "cases",
    "abstractions",
    "response_logs",
    "pi_events",
    "actions",
    "cycles",
    "deficiencies",
    "activities",
    "agreements",
    "bookings",
]


class DB(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.centers = {}
        self.tiers = {}
        self.cases = {}
        self.abstractions = {}
        self.rules = {}
        self.response_logs = {}
        self.pi_events = {}
        self.actions = {}
        self.cycles = {}
        self.deficiencies = {}
        self.activities = {}
        self.agreements = {}
        self.bookings = {}
        self.clock = CLOCK_DEFAULT
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)

    def collection(self, name):
        return getattr(self, name)


db = DB()


def new_id():
    return str(uuid.uuid4())


def clock_now():
    """Current logical-clock instant."""
    return db.clock


def set_clock(value):
    db.clock = value
