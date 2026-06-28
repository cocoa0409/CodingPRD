"""In-memory data store + logical clock.

The store starts EMPTY on every boot. No entity is seeded, preloaded, or
hardcoded at startup. Tests build every precondition via the API surface.
"""
import uuid
from datetime import datetime, timezone

# Logical clock default (PRD §2.4): 2026-01-01T00:00:00Z. Never falls back to
# wall-clock time.
CLOCK_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.properties = {}
        self.room_types = {}
        self.rate_plans = {}
        self.inventory_days = {}
        self.rate_decisions = {}
        self.yield_rules = {}
        self.group_blocks = {}
        self.channel_mappings = {}
        self.competitor_rates = {}
        self.transient_reservations = {}
        # Monotonic creation counter to provide a stable tie-break / insertion
        # order independent of timestamp collisions.
        self._seq = 0
        # Logical clock.
        self.clock = CLOCK_DEFAULT

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with exactly 3 fractional digits (wall clock).

    Used for created_at / updated_at on records. This is real-time, distinct
    from the logical clock which governs forecasting/KPI date math (PRD §2.4).
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_now():
    return db.clock


def clock_date():
    """The logical clock's current date (midnight UTC of the clock day)."""
    c = db.clock
    return datetime(c.year, c.month, c.day, 0, 0, 0, tzinfo=timezone.utc)
