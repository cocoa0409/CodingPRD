"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No seeding, no disk persistence: every entity is created through the API surface.
"""

COLLECTIONS = [
    "dealerships",
    "customers",
    "pricing_contracts",
    "space_plans",
    "typicals",
    "product_series",
    "project_orders",
    "order_lines",
    "crews",
    "install_events",
    "staging_reservations",
    "punch_items",
    "manufacturer_claims",
    "asset_tags",
    "liquidation_lots",
]

db = {name: {} for name in COLLECTIONS}

_seq_counter = [0]


def next_seq() -> int:
    """Monotonic insertion sequence; stabilizes created_at-ascending sorts."""
    _seq_counter[0] += 1
    return _seq_counter[0]
