"""In-memory data store.

The store starts completely empty on every boot. No seeding, no preloading,
no on-disk persistence of any kind.
"""

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
CURRENT_UTC = "2026-08-01T00:00:00.000Z"

# ---------------------------------------------------------------------------
# Entity stores (dicts keyed by id)
# ---------------------------------------------------------------------------
tracks = {}
coaches = {}
track_days = {}
rental_blocks = {}
bookings = {}
drivers = {}
waivers = {}
inspections = {}
sessions = {}
incidents = {}
noise_readings = {}
garage_assignments = {}
paddock_assignments = {}
