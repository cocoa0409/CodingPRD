"""In-memory data store. Fresh on every process boot (per-test-server isolation).
No seeding: every entity is created via the declared API surface."""

COLLECTIONS = [
    "policies",
    "patients",
    "accounts",
    "payments",
    "applications",
    "members",
    "documents",
    "screenings",
    "determinations",
    "adjustments",
    "notices",
    "collection_actions",
    "reports",
]

db = {name: {} for name in COLLECTIONS}
