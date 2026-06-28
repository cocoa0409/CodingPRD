"""In-memory data store. Every byte of state is wiped on each fresh process boot.

NO seeding, preloading, or hardcoded entities. The store starts empty; tests
build all entity data via API calls.
"""
import uuid

from clock import clock, format_iso8601


class Store:
    def __init__(self):
        # One dict per entity type, keyed by id.
        self.pricing_configs = {}
        self.homeowners = {}
        self.homes = {}
        self.hvac_systems = {}
        self.crew_members = {}
        self.route_plans = {}
        self.work_orders = {}
        self.inspections = {}
        self.recurring_plans = {}
        self.upsell_referrals = {}
        self.callback_tickets = {}
        # Monotonic insertion sequence for stable created_at tie-breaks when two
        # rows share the same logical-clock timestamp (created_at uses wall-free
        # logical sequencing only for ordering; the stored created_at value is the
        # logical clock instant).
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Current logical-clock instant formatted as ISO 8601 UTC, 3 fractional digits."""
    return format_iso8601(clock.now())
