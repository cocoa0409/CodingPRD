"""Existence checks (priority 3) — fetch entity or raise ERR_NOT_FOUND."""
from errors import err


def fetch(collection, entity_id):
    ent = collection.get(entity_id)
    if ent is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return ent
