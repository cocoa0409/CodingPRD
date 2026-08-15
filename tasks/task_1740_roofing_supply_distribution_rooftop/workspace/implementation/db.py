"""In-memory data store. Fresh on every process boot (per-test-server
isolation): no seeding, no files, no external persistence."""

COLLECTIONS = [
    "branches",
    "products",
    "inventory_lots",
    "contractor_accounts",
    "job_accounts",
    "takeoffs",
    "orders",
    "order_lines",
    "delivery_slots",
    "deliveries",
    "surge_events",
    "allocations",
    "returns",
    "damage_claims",
    "warranty_registrations",
]

db = {name: {} for name in COLLECTIONS}

# Monotonic insertion sequence: ties created_at ordering when several records
# share a logical-clock instant (created_at ASC, insertion order tie-break).
_seq_counter = [0]


def next_seq() -> int:
    _seq_counter[0] += 1
    return _seq_counter[0]
