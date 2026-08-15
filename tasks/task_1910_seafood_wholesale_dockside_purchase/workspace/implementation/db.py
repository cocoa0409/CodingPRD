"""In-memory data store. The store starts empty on every boot — no seeding.

All records are plain dicts keyed by id. Internal-only fields are prefixed
with an underscore (e.g. ``_seq``, ``_quote_date``) and stripped at
serialization time. ``created_at``/``updated_at`` are stored as datetimes
reading the logical clock (never the wall clock) and formatted on output.
"""
import threading
import uuid
from datetime import datetime, timezone

# Logical clock startup default per PRD section 2.6 — the server never falls
# back to wall-clock time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.vessels = {}
        self.customers = {}
        self.catch_areas = {}
        self.species = {}
        self.quotes = {}
        self.tickets = {}
        self.lines = {}
        self.assessments = {}
        self.lots = {}
        self.orders = {}
        self.order_lines = {}
        self.allocations = {}
        self.shipments = {}
        self.import_docs = {}
        self.holds = {}
        self.substitutions = {}
        self.seq = 0
        self.clock = CLOCK_DEFAULT
        # Single global lock serializes request handling so cascades are atomic.
        self.lock = threading.RLock()


store = Store()


def now():
    """Current logical time (datetime, UTC)."""
    return store.clock


def next_seq():
    store.seq += 1
    return store.seq


def new_record(fields):
    """Create a record dict with the common system fields populated."""
    ts = now()
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """Record a modification: bump version and refresh updated_at."""
    rec["version"] += 1
    rec["updated_at"] = now()
