"""In-memory data store. All entities keyed by id. Starts empty on every boot."""
import uuid

import clock

# One dict per entity type, keyed by id.
lenders = {}
appraisers = {}
properties = {}
orders = {}
assignments = {}
reports = {}
compliance_reviews = {}
revision_requests = {}
reconsiderations = {}
fee_splits = {}
firewall_events = {}


def reset():
    """Clear all stores (used only for safety; not called at import)."""
    for store in (
        lenders, appraisers, properties, orders, assignments, reports,
        compliance_reviews, revision_requests, reconsiderations, fee_splits,
        firewall_events,
    ):
        store.clear()


def new_id():
    return str(uuid.uuid4())


def stamp_create(obj, mutable=True):
    """Set id, created_at and (for mutable entities) updated_at + version."""
    now = clock.now()
    obj["id"] = new_id()
    obj["created_at"] = clock.format_iso(now)
    obj["_created_dt"] = now  # internal sort/tie-break key, not serialized
    if mutable:
        obj["updated_at"] = clock.format_iso(now)
        obj["version"] = 1
    return obj


def touch(obj):
    """Bump updated_at and version on a mutable entity."""
    now = clock.now()
    obj["updated_at"] = clock.format_iso(now)
    obj["version"] = obj.get("version", 1) + 1
    return obj
