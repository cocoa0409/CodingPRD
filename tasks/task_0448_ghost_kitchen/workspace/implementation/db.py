"""In-memory data store. Wiped on every process boot (no persistence).

NEVER seed or preload any entity here. The store starts empty; tests build
all preconditions via the declared API surface.
"""
import threading
import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.7). Default startup value is 2026-01-01T00:00:00Z and
# stays there until POST /_clock/set_current_utc moves it. Never wall-clock.
# ---------------------------------------------------------------------------
_CLOCK_DEFAULT_EPOCH_SECONDS = int(
    datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp()
)


class Store:
    """Holds every collection plus the logical clock. One instance per process."""

    def __init__(self):
        self.lock = threading.RLock()
        # entity collections keyed by id
        self.stalls = {}
        self.brands = {}
        self.leases = {}
        self.equipment = {}
        self.bookings = {}
        self.menu_items = {}
        self.recipe_components = {}
        self.ingredient_lots = {}
        self.orders = {}
        # monotonic sequence used as an absolute creation tiebreak (created_at
        # has only millisecond resolution, so we need a strict total order).
        self._seq = 0
        # logical clock, in whole UTC epoch seconds
        self.clock_epoch_seconds = _CLOCK_DEFAULT_EPOCH_SECONDS

    # -- id / sequence / time helpers ---------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now_iso(self):
        """Server wall-clock timestamp for created_at/updated_at metadata.

        ISO 8601 UTC with exactly three fractional digits (PRD §2.4)."""
        return _iso_millis(datetime.now(timezone.utc))

    def current_clock_minute(self):
        """floor(clock_epoch_seconds / 60) — minutes since the Unix epoch."""
        return self.clock_epoch_seconds // 60


def _iso_millis(dt):
    # Render with milliseconds and a trailing Z.
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


# Single global store instance (per-process; reset on every boot).
store = Store()
