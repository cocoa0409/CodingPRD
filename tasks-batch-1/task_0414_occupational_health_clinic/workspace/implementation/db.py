"""In-memory data store for the Occupational Health Clinic API.

All storage is process-local Python dicts keyed by id. The store starts empty on
every boot; nothing is seeded or preloaded. Tests build all preconditions via the
declared API surface.
"""

import threading
import uuid
from datetime import datetime, timezone


# A single global lock serializes all mutations so multi-step operations stay
# atomic relative to each other (per-test-server isolation makes contention rare,
# but the lock keeps cascades consistent).
LOCK = threading.RLock()


class Store:
    def __init__(self):
        self.employers = {}
        self.protocols = {}
        self.workers = {}
        self.encounters = {}
        self.drug_screens = {}
        self.custody_events = {}
        self.injury_cases = {}
        self.work_statuses = {}
        self.surveillance_exams = {}
        self.clearances = {}
        self.invoices = {}


db = Store()


_seq_counter = [0]


def next_seq():
    """Monotonic global creation sequence, used to break created_at ties so list
    ordering by created_at ASC is deterministic even within the same millisecond."""
    _seq_counter[0] += 1
    return _seq_counter[0]


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits, 'Z' suffix."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
