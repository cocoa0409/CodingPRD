"""Existence + tenant-scoping lookups (ERR_NOT_FOUND, priority 3).

An entity that resolves but belongs to a different salon than required is
treated as not found (PRD §2.8).
"""
import db
from errors import err


def get_or_404(collection, entity_id):
    obj = collection.get(entity_id)
    if obj is None:
        raise err("ERR_NOT_FOUND", "referenced resource not found")
    return obj


def get_salon(salon_id):
    return get_or_404(db.salons, salon_id)


def get_scoped(collection, entity_id, salon_id):
    """Resolve an entity and require it to belong to `salon_id`."""
    obj = collection.get(entity_id)
    if obj is None or obj.get("salon_id") != salon_id:
        raise err("ERR_NOT_FOUND", "referenced resource not found or in another salon")
    return obj
