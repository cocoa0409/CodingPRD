"""In-memory data store and logical clock.

All state is held in module-level dicts that start EMPTY on every boot.
Nothing is seeded, preloaded, or hardcoded — tests build all state via the API.
"""
import uuid
from datetime import datetime, timezone
import threading

# ---------------------------------------------------------------------------
# Logical clock (§2.9). Startup default is 2026-01-01T00:00:00Z; it stays at
# that default until explicitly set and never falls back to wall-clock time.
# ---------------------------------------------------------------------------
_CLOCK_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # One dict per entity collection, keyed by id.
        self.clients = {}
        self.care_packages = {}      # keyed by code (id == code)
        self.supply_kits = {}        # keyed by sku (id == sku)
        self.providers = {}
        self.rooms = {}
        self.episodes = {}
        self.prenatal_visits = {}
        self.on_call_assignments = {}
        self.bookings = {}
        self.insurance_claims = {}
        self.charges = {}
        self.payment_plans = {}
        # Logical clock
        self.logical_clock = _CLOCK_DEFAULT
        # Monotonic counter to break created_at ties for ascending sort.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        """Current logical-clock instant (used for system timestamps)."""
        return self.logical_clock


db = Store()


def new_id():
    """Server-minted UUID with no type prefix (§2.4)."""
    return str(uuid.uuid4())


def iso_now(dt=None):
    """ISO 8601 UTC timestamp with three fractional digits (§2.4)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
