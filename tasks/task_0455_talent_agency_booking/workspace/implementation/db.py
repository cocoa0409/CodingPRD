"""In-memory data store, id/timestamp minting, and the logical clock.

The store starts EMPTY on every boot. Nothing is seeded here.
"""
import uuid
import threading
from datetime import datetime, timezone

# Logical clock default (PRD §2.4): server startup reads exactly this instant
# and never falls back to wall-clock time until explicitly moved.
DEFAULT_CLOCK = "2026-01-01T00:00:00Z"

_lock = threading.RLock()


class Store:
    """Holds one dict per entity collection, keyed by id."""

    def __init__(self):
        self.agencies = {}
        self.casting_directors = {}
        self.talents = {}
        self.comp_cards = {}
        self.casting_calls = {}
        self.submissions = {}
        self.audition_slots = {}
        self.availability_holds = {}
        self.deal_memos = {}
        self.bookings = {}
        self.commission_entries = {}
        self.payments = {}
        self.residual_schedules = {}
        # logical clock, stored as a normalized ISO-8601 UTC string
        self.clock = DEFAULT_CLOCK
        # monotonic sequence so created_at ties have a stable insertion order
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
lock = _lock


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Return current wall-clock as ISO-8601 UTC with three fractional digits.

    Used for created_at / updated_at / api_request_timestamp (record-keeping),
    distinct from the logical clock that drives temporal preconditions.
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
