"""In-memory data store + simulated clock.

Storage is pure in-process Python dicts keyed by UUID. Nothing is persisted to
disk and nothing is seeded at startup — every entity is created by a request
through the declared API surface. A fresh process therefore starts empty.
"""
import uuid
from datetime import datetime, timezone

# ---- collections (entity_name -> { id: record_dict }) ----
COLLECTIONS = [
    "price_tiers",
    "accounts",
    "roast_profiles",
    "products",
    "green_lots",
    "roast_batches",
    "roasted_lots",
    "standing_orders",
    "orders",
    "fulfillments",
    "sample_requests",
    "invoices",
    "payments",
]


class Store:
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        # simulated clock: default to a fixed deterministic instant; tests set it.
        self._clock = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    # ---- id / time helpers ----
    def new_id(self):
        return str(uuid.uuid4())

    def now(self):
        """Wall-clock timestamp for created_at/updated_at bookkeeping (real UTC)."""
        return datetime.now(timezone.utc)

    # ---- simulated clock (test-driving) ----
    def clock(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt


store = Store()


def iso_z(dt):
    """Serialize a datetime to ISO 8601 UTC with three fractional digits + Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
