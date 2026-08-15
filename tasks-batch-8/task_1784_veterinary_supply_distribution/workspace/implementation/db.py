"""In-memory data store. Fresh on every process boot (per-test-server isolation).

The store starts EMPTY on every boot — no seeding anywhere. Every entity a test
needs is constructed via the declared API surface.
"""

COLLECTIONS = [
    "clinics",
    "products",
    "manufacturer_authorizations",
    "inventory_lots",
    "orders",
    "order_lines",
    "backorder_lines",
    "shipments",
    "bundle_programs",
    "bundle_enrollments",
    "rebate_accruals",
    "short_date_credits",
]

db = {name: {} for name in COLLECTIONS}

# Monotonic allocation sequence for BackorderLine.allocation_sequence (1, 2, 3, ...)
# Never derived from record ids.
backorder_sequence = {"next": 1}


def mint_allocation_sequence() -> int:
    val = backorder_sequence["next"]
    backorder_sequence["next"] = val + 1
    return val
