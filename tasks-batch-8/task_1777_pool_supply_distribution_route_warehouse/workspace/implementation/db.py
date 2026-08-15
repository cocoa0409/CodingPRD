"""In-memory data store. Fresh on every process boot (per-test-server isolation).

The store starts EMPTY on every boot — no seeding. Every entity a test needs is
constructed via the declared API surface.
"""

COLLECTIONS = [
    "branches",
    "accounts",
    "products",
    "stock_lots",
    "seasonal_programs",
    "seasonal_commitments",
    "orders",
    "order_lines",
    "backorder_requests",
    "service_centers",
    "warranty_claims",
    "return_authorizations",
]

db = {name: {} for name in COLLECTIONS}

# Monotonic creation sequence — used as the exact "created_at ASC" ordering key
# (wall-clock timestamps can tie within one millisecond on fast test runs).
_seq_counter = [0]


def next_seq() -> int:
    _seq_counter[0] += 1
    return _seq_counter[0]
