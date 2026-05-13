"""Common helpers for entity creation/mutation, OCC, etc."""
import db
from errors import APIError, ERR_VERSION_CONFLICT, ERR_NOT_FOUND


def make_versioned(extra: dict) -> dict:
    base = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
    }
    base.update(extra)
    return base


def make_unversioned(extra: dict) -> dict:
    base = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
    }
    base.update(extra)
    return base


def touch(entity):
    """Bump updated_at and version on an in-place mutation. For versioned entities only."""
    entity["updated_at"] = db.now_iso()
    if "version" in entity:
        entity["version"] = entity.get("version", 0) + 1


def check_version(entity, body):
    """Enforce optimistic concurrency control. Only checked if body provides 'version'."""
    if body is None:
        return
    if "version" not in body or body["version"] is None:
        return
    expected = body["version"]
    if entity.get("version") != expected:
        raise APIError(ERR_VERSION_CONFLICT, 409, "Version mismatch")


def get_or_404(store, ent_id):
    if ent_id not in store:
        raise APIError(ERR_NOT_FOUND, 404, "Resource not found")
    return store[ent_id]
