"""Shared helpers for route modules: existence (gate 4) and ownership (gate 2)."""

from db import store
from errors import not_found
from middleware import forbidden


def get_or_404(mapping, rid, what="resource"):
    rec = mapping.get(rid)
    if rec is None:
        raise not_found(f"{what} {rid} does not exist")
    return rec


# ---------------------------------------------------------------------------
# Customer entity-backed ownership (PRD §2.1): the resource's customer foreign
# key is compared to X-User-ID. Other roles carry opaque identifiers and are
# never compared to entity ids.
# ---------------------------------------------------------------------------
def resource_customer_id(kind, rec):
    """The customer foreign key of a resource, following parent links."""
    if rec is None:
        return None
    if kind == "customer":
        return rec["id"]
    if kind in ("machine", "window", "offer"):
        return rec["customer_id"]
    if kind == "project":
        return rec["customer_id"]
    if kind == "assessment":
        machine = store.machines.get(rec["machine_id"])
        return machine["customer_id"] if machine else None
    if kind in ("test", "training", "stage", "claim"):
        project = store.projects.get(rec["project_id"])
        return project["customer_id"] if project else None
    return None


def check_customer_ownership(user_id, role, kind, rec):
    """For Customer callers on an existing resource: 403 when not the owner."""
    if role != "Customer":
        return
    if rec is None:
        return
    if resource_customer_id(kind, rec) != user_id:
        raise forbidden("customer does not own this resource")


def customer_owns(user_id, kind, rec):
    return resource_customer_id(kind, rec) == user_id
