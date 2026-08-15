"""In-memory data store. Fresh on every process boot (per-test-server isolation).

The store starts EMPTY on every boot — no seeding. Every entity a test needs is
constructed through the declared API surface.
"""

COLLECTIONS = [
    "programs",
    "retention_policies",
    "storage_locations",
    "venues",
    "claimants",
    "items",
    "claims",
    "inquiries",
    "auction_events",
    "auction_lots",
    "lot_items",
    "referrals",
    "release_records",
]

db = {name: {} for name in COLLECTIONS}
