"""In-memory data store.

Every entity collection is a dict keyed by id. The store starts EMPTY on
every boot — no seeding, no preload. Tests build all state via the API.

Common fields on each record:
  id, created_at, updated_at, version (starts at 1, increments on mutation)
"""
from util import new_id, iso
from services import clock

# One dict per entity type.
customers = {}
projects = {}
design_consults = {}
space_measures = {}
component_configs = {}
quotes = {}
deposits = {}
manufacture_orders = {}
crews = {}
install_jobs = {}
change_orders = {}
warranty_claims = {}
financing_applications = {}

_ALL = [
    customers, projects, design_consults, space_measures, component_configs,
    quotes, deposits, manufacture_orders, crews, install_jobs, change_orders,
    warranty_claims, financing_applications,
]


def reset():
    for d in _ALL:
        d.clear()


def stamp_new(record: dict) -> dict:
    """Attach common system fields to a freshly created record."""
    now = clock.now()
    record["id"] = record.get("id") or new_id()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    return record


def touch(record: dict):
    """Mutation: refresh updated_at and increment version by one."""
    record["updated_at"] = clock.now()
    record["version"] = record["version"] + 1
