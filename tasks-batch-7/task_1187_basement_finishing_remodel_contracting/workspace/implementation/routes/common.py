"""Shared helpers for route modules: entity resolution, ownership, lists."""
from db import stores, new_id, next_seq, now_ts
from errors import fail
from response import ok_list
from validation import pagination


def get_or_404(store, entity_id, what):
    e = stores[store].get(entity_id)
    if e is None:
        fail("ERR_NOT_FOUND", "%s not found" % what)
    return e


def project_or_404(project_id):
    return get_or_404("projects", project_id, "Project")


def require_project_owner(project, role, uid):
    """Priority 3: entity-backed callers own the project (PRD §2.1)."""
    if role == "Contractor" and project["contractor_id"] != uid:
        fail("ERR_NOT_RESOURCE_OWNER", "Contractor does not own this project")
    if role == "Homeowner" and project["homeowner_id"] != uid:
        fail("ERR_NOT_RESOURCE_OWNER", "Homeowner does not own this project")


def require_contractor_owner(project, uid):
    if project["contractor_id"] != uid:
        fail("ERR_NOT_RESOURCE_OWNER", "Contractor does not own this project")


def require_homeowner_owner(project, uid):
    if project["homeowner_id"] != uid:
        fail("ERR_NOT_RESOURCE_OWNER", "Homeowner does not own this project")


def new_entity(extra):
    e = {
        "id": new_id(),
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "version": 1,
        "_seq": next_seq(),
    }
    e.update(extra)
    return e


def sorted_items(items):
    """All list endpoints sort by created_at ascending (PRD §2.3); the
    insertion sequence is a stable internal tiebreak."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def list_response(items, serializer):
    limit, offset = pagination()
    ordered = sorted_items(items)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([serializer(e) for e in page], total, limit, offset)
