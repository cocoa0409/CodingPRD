"""In-memory data store. All state lives in module-level dicts keyed by id.

The store starts EMPTY on every process boot. Nothing is seeded or preloaded.
"""

# One dict per entity type, keyed by id.
breeds = {}
service_tiers = {}
add_ons = {}
customers = {}
pets = {}
vaccination_records = {}
groomers = {}
vans = {}
route_days = {}
route_stops = {}
appointments = {}
appointment_add_ons = {}
recurring_plans = {}
fee_charges = {}

_ALL = [
    breeds, service_tiers, add_ons, customers, pets, vaccination_records,
    groomers, vans, route_days, route_stops, appointments,
    appointment_add_ons, recurring_plans, fee_charges,
]


def reset():
    for d in _ALL:
        d.clear()
