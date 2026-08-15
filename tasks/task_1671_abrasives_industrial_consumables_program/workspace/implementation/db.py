"""In-memory data store. Fresh on every process boot (per-test-server isolation).

The store starts EMPTY: no seeding, no preloaded entities. Every entity a test
needs is built through the declared API surface.
"""

COLLECTIONS = [
    "products",
    "machines",
    "lots",
    "standards",
    "usage_records",
    "contracts",
    "contract_lines",
    "blanket_orders",
    "releases",
    "trials",
    "disposal_records",
]

db = {name: {} for name in COLLECTIONS}
