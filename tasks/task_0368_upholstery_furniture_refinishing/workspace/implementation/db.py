"""In-memory data store. All state is process-local and wiped on every boot.

The store starts empty on every boot — NO entity seeding at startup.
Tests construct every entity via the declared API surface.
"""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # One dict per entity, keyed by id.
        self.customers = {}
        self.fabric_skus = {}
        self.foam_specs = {}
        self.work_orders = {}
        self.condition_photos = {}
        self.line_items = {}
        self.estimates = {}
        self.material_orders = {}
        self.shop_days = {}
        self.fulfillment_legs = {}
        self.warranty_claims = {}
        self.payments = {}
        # Test-driving server clock (used to stamp completed_at). None => real now.
        self.clock_override = None
        # Monotonic counter to guarantee strict created_at ordering even when
        # two records are minted within the same clock tick.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def _fmt(dt):
    # ISO 8601 UTC with exactly three fractional digits, trailing Z.
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{int(dt.microsecond / 1000):03d}Z"


def now_iso():
    """Wall-clock now (request timestamps / created_at), millisecond precision."""
    return _fmt(datetime.now(timezone.utc))


def server_clock_iso():
    """The test-driving server clock used to stamp completed_at.

    Uses the override instant set via POST /_clock/set_current_utc when present,
    otherwise falls back to wall-clock now.
    """
    if db.clock_override is not None:
        return db.clock_override
    return now_iso()
