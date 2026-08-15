"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No entity is seeded at startup: every record is created through the declared
API surface by the tests themselves.
"""

COLLECTIONS = [
    "jurisdiction_profiles",
    "properties",
    "units",
    "tenancies",
    "inspections",
    "inspection_items",
    "deductions",
    "statements",
    "disputes",
    "disbursements",
]

db = {name: {} for name in COLLECTIONS}
