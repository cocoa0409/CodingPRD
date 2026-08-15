"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No seeding: every entity is constructed via the declared API surface.
"""

COLLECTIONS = [
    "contracts",
    "bid_items",
    "work_packages",
    "crews",
    "equipment",
    "assignments",
    "production_entries",
    "stock_items",
    "material_issues",
    "inspections",
    "outage_requests",
    "storm_activations",
    "safety_events",
    "invoices",
]

db = {name: {} for name in COLLECTIONS}
