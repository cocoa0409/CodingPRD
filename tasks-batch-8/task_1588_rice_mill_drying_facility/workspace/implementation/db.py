"""In-memory data store. Fresh on every process boot (per-test-server isolation).
No seeding: every entity is created through the declared API surface."""

COLLECTIONS = [
    "seasons",
    "growers",
    "contracts",
    "bins",
    "lots",
    "drying_runs",
    "mill_runs",
    "packaging_runs",
    "byproduct_orders",
    "fumigation_events",
    "holds",
    "settlements",
]

db = {name: {} for name in COLLECTIONS}
