"""In-memory data store. All state is wiped on every process restart.

NO seeding/preloading: every dict starts empty and is only populated via the
declared API surface at request time.
"""
import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Logical clock (test-driven; controls bid_deadline / license_expiry gating)
# ---------------------------------------------------------------------------
class _Clock:
    def __init__(self):
        self._current = None  # None => use wall clock

    def now(self):
        if self._current is not None:
            return self._current
        return datetime.now(timezone.utc)

    def set(self, dt):
        self._current = dt


clock = _Clock()


# ---------------------------------------------------------------------------
# Collections — one dict per entity, keyed by id
# ---------------------------------------------------------------------------
homeowners = {}
contractors = {}
projects = {}
scope_line_items = {}
bids = {}
bid_line_items = {}
milestones = {}
escrows = {}
draws = {}
lien_waivers = {}
change_orders = {}
disputes = {}


def new_id():
    return str(uuid.uuid4())


def iso_now():
    """Server timestamp: ISO 8601 UTC with exactly three fractional digits + 'Z'."""
    dt = clock.now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
