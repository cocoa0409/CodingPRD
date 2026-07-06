"""Common helpers for entity stamps."""
from clock import iso_now
from db import new_id


def stamp_common(full: bool = True):
    """Return id/created_at/updated_at/version dict.
    full=False -> only id + created_at (append-only reduced fields)."""
    now = iso_now()
    if full:
        return {
            "id": new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 0,
        }
    return {
        "id": new_id(),
        "created_at": now,
    }


def bump(entity: dict):
    """Increment version and refresh updated_at."""
    entity["version"] = entity.get("version", 0) + 1
    entity["updated_at"] = iso_now()
