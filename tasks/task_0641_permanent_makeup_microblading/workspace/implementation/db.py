"""In-memory data store. All state is plain Python dicts keyed by id.

The store starts EMPTY on every boot. Nothing is seeded, preloaded, or
hardcoded. Tests build every entity via the declared API surface.
"""
import uuid
from datetime import timezone

from clock import clock


def new_id():
    return str(uuid.uuid4())


def iso_ms(dt):
    """ISO 8601 UTC, three fractional digits (PRD 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso_ms(clock.now())


class Store:
    def __init__(self):
        self.studios = {}
        self.technicians = {}
        self.clients = {}
        self.consent_records = {}
        self.patch_tests = {}
        self.color_formulas = {}
        self.appointments = {}
        self.package_orders = {}
        self.deposit_transactions = {}
        self.healing_logs = {}
        self.redo_requests = {}
        # Monotonic creation sequence to make created_at ordering deterministic
        # when multiple resources share the same logical-clock timestamp.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
