"""Path-existence (ERR_NOT_FOUND) and FK-resolution (ERR_FK_NOT_FOUND) helpers,
plus entity-backed ownership checks (ERR_NOT_RESOURCE_OWNER)."""
import db
from errors import (fail, ERR_NOT_FOUND, ERR_FK_NOT_FOUND,
                    ERR_NOT_RESOURCE_OWNER)


def path_get(collection, rid):
    """Resolve a path-referenced id or raise ERR_NOT_FOUND (priority 3)."""
    rec = collection.get(rid)
    if rec is None:
        fail(ERR_NOT_FOUND, "Resource not found")
    return rec


def fk_get(collection, rid):
    """Resolve a body foreign-key id or raise ERR_FK_NOT_FOUND (priority 4)."""
    rec = collection.get(rid)
    if rec is None:
        fail(ERR_FK_NOT_FOUND, "Referenced entity does not exist")
    return rec


def require_owner(resource_rightsholder_id, user_id, role):
    """Priority 7: entity-backed actor must own the resource. Operators
    (Administrator/RoyaltyOperator) are opaque and skip ownership."""
    if role in ("Licensee", "Rightsholder"):
        if resource_rightsholder_id != user_id:
            fail(ERR_NOT_RESOURCE_OWNER, "Actor does not own this resource")
