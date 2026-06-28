"""In-memory data store + logical clock.

The store starts EMPTY on every process boot. Nothing is seeded, preloaded, or
hardcoded; tests build all state through the declared API surface. Per-test-server
isolation re-launches this process before every test, wiping state by design.
"""
import uuid
from datetime import datetime, timezone

# Logical clock default at startup (PRD §2.4): exactly 2026-04-01T00:00:00Z.
CLOCK_DEFAULT = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    """One collection (dict id -> record) per entity type."""

    def __init__(self):
        self.gardens = {}
        self.membership_plans = {}
        self.memberships = {}
        self.time_slots = {}
        self.reservations = {}
        self.event_tickets = {}
        self.program_sessions = {}
        self.registrations = {}
        self.venues = {}
        self.rentals = {}
        self.donations = {}
        self.conservancy_funds = {}
        # Logical clock (PRD §2.4): starts at the fixed default, never wall-clock.
        self.now = CLOCK_DEFAULT
        # Monotonic counter to make created_at strictly orderable even when two
        # records are created within the same logical clock tick.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    """Server-minted id: a UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def iso(dt):
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now():
    return db.now
