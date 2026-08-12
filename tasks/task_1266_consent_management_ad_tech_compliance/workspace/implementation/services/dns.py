"""Do-not-sell request services: in-scope vendor selection and the
propagation counter invariant (total == pending + confirmed + failed)."""
from db import store


def in_scope_vendors(request_entity):
    """APPROVED vendors of the request's property whose declared_purposes
    intersect the request's scope_categories, in vendor created_at ASC order."""
    scope = set(request_entity.get("scope_categories") or [])
    vendors = [
        v
        for v in store["vendors"].values()
        if v.get("property_id") == request_entity.get("property_id")
        and v.get("status") == "APPROVED"
        and scope.intersection(v.get("declared_purposes") or [])
    ]
    vendors.sort(key=lambda v: v.get("created_at") or "")
    return vendors


def has_open_propagation(request_id, vendor_id):
    """True when the vendor already holds a PENDING or CONFIRMED propagation
    on this request (re-dispatch skips those vendors)."""
    return any(
        p.get("request_id") == request_id
        and p.get("vendor_id") == vendor_id
        and p.get("status") in ("PENDING", "CONFIRMED")
        for p in store["vendor_propagations"].values()
    )


def request_children(request_id):
    children = [
        p
        for p in store["vendor_propagations"].values()
        if p.get("request_id") == request_id
    ]
    children.sort(key=lambda p: p.get("created_at") or "")
    return children


def recompute_request_counters(request_entity):
    """Recompute the four counters and re-evaluate propagation_status:
    pending > 0 -> PROPAGATING; pending == 0 and failed == 0 -> ALL_CONFIRMED;
    pending == 0 and failed > 0 -> PARTIAL_FAILURE."""
    children = request_children(request_entity.get("id"))
    pending = sum(1 for c in children if c.get("status") == "PENDING")
    confirmed = sum(1 for c in children if c.get("status") == "CONFIRMED")
    failed = sum(1 for c in children if c.get("status") == "FAILED")
    request_entity["total_propagations"] = len(children)
    request_entity["pending_count"] = pending
    request_entity["confirmed_count"] = confirmed
    request_entity["failed_count"] = failed
    if pending > 0:
        request_entity["propagation_status"] = "PROPAGATING"
    elif failed == 0:
        request_entity["propagation_status"] = "ALL_CONFIRMED"
    else:
        request_entity["propagation_status"] = "PARTIAL_FAILURE"
