"""In-memory data store (PRD §2 — API correctness, not durability).

Every collection is a plain dict keyed by id. The store is module-level state
that starts EMPTY on every process boot. Nothing is seeded, preloaded, or
hardcoded here — under per-test-server isolation each test builds all state it
needs via the declared API surface.
"""

# Primary collections keyed by id.
shops = {}
service_packages = {}
inspection_items = {}
coupons = {}
fleet_accounts = {}
vehicles = {}
bays = {}
technicians = {}
queue_tickets = {}
work_orders = {}
work_order_lines = {}
service_stickers = {}
payments = {}

# Per-shop monotonic intake counter for QueueTicket.queue_seq (PRD §3.3).
_queue_seq_counter = {}


def next_queue_seq(shop_id: str) -> int:
    """Return the next monotonic intake sequence number for a shop."""
    cur = _queue_seq_counter.get(shop_id, 0) + 1
    _queue_seq_counter[shop_id] = cur
    return cur
