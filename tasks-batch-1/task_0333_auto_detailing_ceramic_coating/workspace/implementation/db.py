"""In-memory data store. All state lives in module-level dicts keyed by id.

Every process boot starts empty — nothing is seeded. The test harness builds
all state via the API. Insertion order of Python 3.7+ dicts gives us the
creation-ascending ordering that list endpoints require; a monotonic sequence
counter breaks ties when several rows share a created_at timestamp.
"""
import uuid

# One dict per entity type, keyed by id.
customers = {}
memberships = {}
service_bays = {}
mobile_units = {}
packages = {}            # PackageCatalog
vehicle_size_rates = {}  # VehicleSizeRate
addons = {}              # AddOn catalog
appointments = {}
appointment_addons = {}  # AppointmentAddOn lines
job_photos = {}
rework_claims = {}

_seq = 0


def reset():
    global _seq
    for d in (customers, memberships, service_bays, mobile_units, packages,
              vehicle_size_rates, addons, appointments, appointment_addons,
              job_photos, rework_claims):
        d.clear()
    _seq = 0


def new_id():
    return str(uuid.uuid4())


def next_seq():
    global _seq
    _seq += 1
    return _seq
