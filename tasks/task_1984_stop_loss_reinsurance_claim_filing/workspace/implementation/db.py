"""In-memory data store. Fresh on every process boot (per-test-server isolation).

The store starts empty on every boot — no seeding. Every entity a test needs is
constructed through the declared API surface.
"""

COLLECTIONS = [
    "plans",
    "contracts",
    "lasers",
    "members",
    "claims",
    "accumulations",
    "filings",
    "line_items",
    "reimbursements",
    "forecasts",
    "audits",
]

db = {name: {} for name in COLLECTIONS}
