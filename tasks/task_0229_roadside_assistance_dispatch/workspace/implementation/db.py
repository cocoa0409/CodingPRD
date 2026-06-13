"""In-memory data store. Starts empty on every boot. No seeding."""
import uuid

import clock

# One dict per entity collection, keyed by id (str UUID).
membership_plans = {}
members = {}
service_providers = {}
provider_shifts = {}
depots = {}
bay_reservations = {}
service_calls = {}
dispatch_offers = {}
reimbursement_claims = {}


def new_id():
    return str(uuid.uuid4())


def stamp_create(record):
    """Set id/created_at/updated_at/version on a freshly created record."""
    ts = clock.now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    """Bump version and updated_at on a mutation."""
    record["version"] += 1
    record["updated_at"] = clock.now_iso()
    return record
