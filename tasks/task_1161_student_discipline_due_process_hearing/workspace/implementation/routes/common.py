"""Shared route helpers: existence checks, guardian scoping, list rendering."""
from errors import raise_err, ERR_NOT_FOUND, ERR_OWNERSHIP_MISMATCH
from db import db, sorted_all, serialize
from middleware import pagination_params
from response import success_list


def get_or_404(coll, entity_id, label="resource"):
    if not isinstance(entity_id, str) or entity_id not in coll:
        raise_err(ERR_NOT_FOUND, f"{label} not found: {entity_id}")
    return coll[entity_id]


def guardian_owns(ctx, student):
    """ParentGuardian X-User-ID must equal student.guardian_id (PRD §2.1)."""
    if ctx.role == "ParentGuardian" and ctx.user_id != student["guardian_id"]:
        raise_err(ERR_OWNERSHIP_MISMATCH, "guardian does not own this student record")


def render_list(coll, filters=None, serializer=None):
    """Sorted by created_at ascending; limit/offset pagination in meta."""
    items = sorted_all(coll)
    if filters:
        for key, value in filters.items():
            if value is not None:
                items = [e for e in items if e.get(key) == value]
    total = len(items)
    limit, offset = pagination_params()
    page = items[offset : offset + limit]
    ser = serializer or (lambda e: serialize(e))
    return success_list([ser(e) for e in page], total, limit, offset)
