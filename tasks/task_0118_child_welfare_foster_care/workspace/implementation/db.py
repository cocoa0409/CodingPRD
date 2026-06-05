"""In-memory data store.

Every entity collection is a plain dict keyed by the entity's UUID `id`. State
lives only in process memory: a fresh process boot (start.sh re-invocation under
--isolation per-test-server) wipes every byte. NOTHING is seeded, preloaded, or
hardcoded here — every entity is constructed by tests via the declared API.

Common system fields (PRD §2.4): every resource carries `id` (UUID, no prefix),
`created_at`, `updated_at` (ISO 8601 UTC, 3 fractional digits) and an integer
`version`. A freshly created resource has version 1; every mutation increments
version by one and refreshes updated_at to the current logical clock.
"""
import uuid

import clock

# One dict per entity type, keyed by id. All empty at boot.
caseworkers = {}
referrals = {}
investigations = {}
cases = {}
children = {}
foster_homes = {}
caregiver_screenings = {}
placements = {}
case_plans = {}
visitations = {}
hearings = {}

# Map entity type name -> its store, for generic lookups.
STORES = {
    "Caseworker": caseworkers,
    "Referral": referrals,
    "Investigation": investigations,
    "Case": cases,
    "Child": children,
    "FosterHome": foster_homes,
    "CaregiverScreening": caregiver_screenings,
    "Placement": placements,
    "CasePlan": case_plans,
    "Visitation": visitations,
    "Hearing": hearings,
}


def new_id():
    return str(uuid.uuid4())


def stamp_create(record):
    """Set id (if absent), created_at, updated_at, version=1 on a new record."""
    ts = clock.iso(clock.now())
    if "id" not in record or record["id"] is None:
        record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def bump(record):
    """Increment version by one and refresh updated_at to the current clock."""
    record["version"] = record.get("version", 0) + 1
    record["updated_at"] = clock.iso(clock.now())
    return record


def reset():
    """Clear all collections. For a clean boot/test isolation; not called at import-time seeding."""
    for store in STORES.values():
        store.clear()
