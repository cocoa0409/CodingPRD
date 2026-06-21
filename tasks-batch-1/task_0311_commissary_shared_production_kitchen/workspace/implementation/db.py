"""In-memory data store.

Every entity collection is a dict keyed by UUID string. A single re-entrant lock
guards all mutations so that concurrent requests (the race tests) serialize.

The store starts EMPTY on every boot. Nothing is seeded — tests build all
preconditions through the declared API surface.
"""
import threading
import uuid
from datetime import datetime, timezone

# One re-entrant global lock. The OCC + capacity races must serialize.
LOCK = threading.RLock()

# Monotonic insertion counter for stable created_at ordering and tie-breaks.
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC with three fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.members = {}
        self.stations = {}
        self.bookings = {}
        self.storage_units = {}
        self.storage_assignments = {}
        self.ingredients = {}
        self.recipes = {}
        self.recipe_components = {}
        self.production_batches = {}
        self.temp_logs = {}
        self.ingredient_orders = {}
        self.event_packouts = {}
        self.invoices = {}


db = Store()
