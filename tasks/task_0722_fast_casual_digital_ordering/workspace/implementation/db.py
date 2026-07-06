"""In-memory data store. Starts empty on every boot — NO seeding."""
import itertools
import uuid
from datetime import datetime, timezone

from response import now_iso

# Logical clock default (PRD §2.11)
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"


class Store:
    def __init__(self):
        # one dict per entity type, keyed by id
        self.stores = {}
        self.menu_items = {}
        self.modifiers = {}
        self.pickup_slots = {}
        self.customers = {}
        self.loyalty_accounts = {}
        self.points_ledger_entries = {}
        self.subscription_plans = {}
        self.subscriptions = {}
        self.orders = {}
        self.order_lines = {}
        self.loyalty_challenges = {}

        # monotonic creation sequence for stable sort by creation order
        self._seq = itertools.count()

        # logical clock
        self.clock_now_iso = CLOCK_DEFAULT

    # ------- id / common fields -------
    def new_id(self):
        return str(uuid.uuid4())

    def common_fields(self):
        ts = now_iso()
        return {
            "id": self.new_id(),
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": next(self._seq),
        }

    def touch(self, entity):
        """Mutation: refresh updated_at and bump version (PRD §2.4)."""
        entity["updated_at"] = now_iso()
        entity["version"] = entity.get("version", 1) + 1

    # ------- clock -------
    def clock_dt(self):
        return parse_iso(self.clock_now_iso)


def parse_iso(s):
    """Parse an ISO 8601 UTC timestamp into an aware datetime."""
    if s is None:
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


db = Store()
