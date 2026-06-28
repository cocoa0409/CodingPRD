"""Entity bookkeeping helpers: common system fields, touch (mutation), lookups.

Common fields (PRD §2.4): id (UUID, no prefix), created_at (ISO8601 UTC, 3
fractional digits), updated_at (refreshed on mutation), version (starts at 1,
+1 per modification). CanteenTransaction is the sole exception — id + created_at
only, never mutated.
"""
import db
from errors import ApiError
import errors


def base_fields():
    """Create the common system fields for a versioned entity.

    Stores both the datetime objects (for ordering / comparison) and is keyed by
    a monotonic creation sequence to disambiguate equal created_at instants.
    """
    created = db.now()
    return {
        "id": db.new_id(),
        "created_at_dt": created,
        "updated_at_dt": created,
        "version": 1,
        "_seq": db.next_seq(),
    }


def event_fields():
    """Common fields for an append-only event (id + created_at only)."""
    created = db.now()
    return {
        "id": db.new_id(),
        "created_at_dt": created,
        "_seq": db.next_seq(),
    }


def touch(entity):
    """Record a mutation: refresh updated_at to the logical clock and bump
    version by one. (PRD §2.4, §2.5)
    """
    entity["updated_at_dt"] = db.now()
    entity["version"] = entity["version"] + 1


def require(table, resource_id):
    """Return the entity or raise ERR_NOT_FOUND (404)."""
    ent = table.get(resource_id)
    if ent is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Resource not found.")
    return ent


def guardian_owns_camper(user_id, role, camper):
    """Ownership check for Guardian-owned resources (PRD §2.1, §3.10).

    Only enforced when acting as Guardian. Raises ERR_NOT_RESOURCE_OWNER (403)
    when X-User-ID does not match the camper's owning guardian.
    """
    if role != "Guardian":
        return
    if camper["guardian_user_id"] != user_id:
        raise ApiError(errors.ERR_NOT_RESOURCE_OWNER, 403, "Not the owner of this resource.")


def sort_by_created(items):
    """Sort by created_at ascending (PRD §2.3), tie-break on creation seq."""
    return sorted(items, key=lambda e: (e["created_at_dt"], e["_seq"]))


def paginate(items, limit, offset):
    """Return (page_items, total_count) after sorting ascending by created_at."""
    ordered = sort_by_created(items)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
