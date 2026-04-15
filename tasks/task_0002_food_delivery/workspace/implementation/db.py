"""In-memory data store for all entities."""

import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC with exactly 3 fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---- stores (dict keyed by id) ----
restaurants = {}
menu_items = {}
customers = {}
riders = {}
orders = {}
order_items = {}        # keyed by id; also grouped by order_id
deliveries = {}
promotions = {}
ratings = {}
complaints = {}
settlements = {}
surge_zones = {}
rider_penalty_logs = {}
wallet_transactions = {}

# helper indexes
promotion_uses_by_customer = {}   # (promotion_id, customer_id) -> count
