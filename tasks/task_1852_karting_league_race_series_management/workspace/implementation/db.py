"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No seeding: the store starts empty; tests construct all entities via the API.
"""

COLLECTIONS = [
    "seasons",
    "classes",
    "drivers",
    "karts",
    "events",
    "entries",
    "inspections",
    "sessions",
    "results",
    "incidents",
    "bookings",
]

db = {name: {} for name in COLLECTIONS}
