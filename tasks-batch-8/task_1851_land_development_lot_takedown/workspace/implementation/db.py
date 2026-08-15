"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No seeding: the store starts empty; tests construct all entities via the API.
"""

COLLECTIONS = [
    "parcels",
    "phases",
    "bonds",
    "builders",
    "agreements",
    "lots",
    "closings",
    "loans",
    "draws",
    "hoas",
    "providers",
    "connections",
]

db = {name: {} for name in COLLECTIONS}
