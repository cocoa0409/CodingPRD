"""In-memory data store + test-driving simulated clock.

Storage is purely in-memory (dicts keyed by id). The store starts EMPTY on
every boot; nothing is seeded, preloaded, or hardcoded. Per-test-server
isolation wipes all state by re-launching the process, so a fresh boot starts
clean.
"""
import threading
import uuid
from datetime import datetime, timezone

# Fixed epoch the simulated clock begins at (SCAFFOLD ClockState.default;
# PRD §2.9 "It begins at a fixed epoch").
CLOCK_EPOCH = datetime(2026, 1, 1, 0, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        # One dict per entity type, keyed by id.
        self.shops = {}
        self.storage_bins = {}
        self.state_schedules = {}
        self.customers = {}
        self.pawn_items = {}
        self.loans = {}
        self.finance_transactions = {}
        self.inventory_items = {}
        self.layaway_plans = {}
        self.layaway_installments = {}
        self.police_holds = {}
        self.cash_drawers = {}

        # Monotonic creation sequence so list sorts are stable in creation order
        # even when two resources share a created_at instant (PRD §2.3 sorts by
        # creation timestamp ascending).
        self._seq = 0

        # Simulated wall clock (PRD §2.9 / ClockState). Begins at the fixed epoch.
        self._clock = CLOCK_EPOCH
        self.lock = threading.RLock()

    def next_seq(self):
        self._seq += 1
        return self._seq

    # --- simulated clock ---
    def now(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 timestamp into an aware UTC datetime, or None on failure."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# Single global store instance — created EMPTY at import, never seeded.
store = Store()
