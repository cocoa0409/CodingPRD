"""In-memory data store. Every collection is a dict keyed by entity id.

State is process-local and wiped on every fresh boot — nothing is seeded,
preloaded, or persisted to disk. The test harness relaunches the server before
each test, so a fresh process == an empty store.
"""

import uuid
from datetime import datetime, timezone

# Logical clock — PRD §2.4. Startup default is exactly 2026-03-01T00:00:00Z and
# never falls back to wall-clock time.
_CLOCK_DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.households = {}
        self.fee_schedules = {}
        self.clients = {}
        self.investment_policy_statements = {}
        self.portfolios = {}
        self.accounts = {}
        self.fee_runs = {}
        self.financial_plans = {}
        self.goals = {}
        self.rebalance_orders = {}
        self.reviews = {}
        self.compliance_items = {}
        # Logical clock
        self.clock = _CLOCK_DEFAULT

    # --- id / timestamp helpers ---
    def new_id(self):
        return str(uuid.uuid4())

    def now_iso(self):
        """Server wall-clock timestamp for created_at/updated_at/meta — ISO 8601
        UTC with three fractional digits (PRD §2.2/§2.4)."""
        return _iso_ms(datetime.now(timezone.utc))

    # --- logical clock ---
    def clock_now(self):
        return self.clock

    def clock_date(self):
        return self.clock.date()

    def set_clock(self, dt):
        self.clock = dt


def _iso_ms(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


db = Store()
