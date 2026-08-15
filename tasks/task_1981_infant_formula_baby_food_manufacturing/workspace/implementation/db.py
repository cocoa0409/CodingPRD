"""In-memory data store and logical clock. Store starts empty on every boot;
nothing is seeded. All state lives in module-level dicts keyed by id."""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.users = {}
        self.profiles = {}
        self.suppliers = {}
        self.audits = {}
        self.ingredients = {}
        self.lots = {}
        self.formulas = {}
        self.batches = {}
        self.validations = {}
        self.labels = {}
        self.complaints = {}
        self.recalls = {}
        self.scopes = {}
        self.plans = {}
        self.entries = {}
        # Monotonic insertion sequence used as a deterministic tie-break
        # whenever created_at values collide under the frozen logical clock.
        self.seq = 0
        # Reference-number counters keyed by (prefix, YYYYMMDD).
        self.ref_counters = {}
        # Logical clock: defaults to 2026-08-01T00:00:00Z per PRD section 2.9.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def next_seq(self):
        self.seq += 1
        return self.seq

    def next_ref(self, prefix):
        date_key = self.clock.strftime("%Y%m%d")
        key = (prefix, date_key)
        self.ref_counters[key] = self.ref_counters.get(key, 0) + 1
        return "%s-%s-%04d" % (prefix, date_key, self.ref_counters[key])


store = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    return store.clock


def set_clock(dt):
    store.clock = dt
