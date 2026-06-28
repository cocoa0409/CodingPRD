"""In-memory data store.

Per-test-server isolation: the process is restarted before every test, so a fresh
module import = a fresh empty store. NOTHING is seeded here. Every entity is built
by tests through the API.

Storage is plain dicts keyed by UUID id. created_at timestamps use real wall-clock
UTC (they are server-stamped audit metadata, not logical-clock dates); logical-clock
DATES are stamped separately from clock.py where the PRD requires them.
"""
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits (created_at/updated_at)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.inns = {}
        self.rooms = {}
        self.rate_periods = {}
        self.packages = {}
        self.guests = {}
        self.gift_certificates = {}
        self.bookings = {}
        self.breakfast_plans = {}
        self.ledger_entries = {}
        self.housekeeping_tasks = {}
        self.tax_remittances = {}
        # Monotonic insertion counter to provide a stable created_at tiebreak for
        # sorting (created_at strings can collide at millisecond resolution).
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
