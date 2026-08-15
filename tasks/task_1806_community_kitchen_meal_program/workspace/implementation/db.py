"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No seeding: the store starts empty; every entity is created via the API surface.
"""

COLLECTIONS = [
    "sites",
    "menu_days",
    "menu_items",
    "food_batches",
    "batch_allocations",
    "volunteers",
    "volunteer_shifts",
    "guests",
    "meal_services",
    "meal_orders",
    "equipment_assets",
    "waste_logs",
]

db = {name: {} for name in COLLECTIONS}

# Maintenance windows recorded per asset for the closed-interval overlap rule:
# asset_id -> list of (start, end) datetimes for IN_MAINTENANCE bookings.
maintenance_windows = {}

# Re-inspection round counters per batch (audit).
inspection_rounds = {}
