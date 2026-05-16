"""Authorization state projection onto Child rows (PRD §2.8, SCAFFOLD calc: child_authorization_state_projection)."""

from clock import clock, parse_iso
from db import db, touch


def _kind_status_for_child(child_id, kind, now):
    """Compute MEDICAL or PICKUP status for the given child at the given clock instant."""
    has_any = False
    has_active = False
    for auth in db.authorizations.values():
        if auth["child_id"] != child_id or auth["kind"] != kind:
            continue
        has_any = True
        if auth["status"] != "ACTIVE":
            continue
        eff = parse_iso(auth["effective_at"])
        exp = parse_iso(auth["expires_at"])
        if eff <= now < exp:
            has_active = True
    if has_active:
        return "ACTIVE"
    if has_any:
        return "EXPIRED"
    return "NONE"


def project_child_auth_statuses(child, persist=True):
    """Project medical / pickup status onto a Child row.

    If persist=True and any value changed, also bumps the child's
    version + updated_at (this is a system-driven mutation per §2.8).
    Returns the (possibly mutated) child dict.
    """
    now = clock.now()
    new_med = _kind_status_for_child(child["id"], "MEDICAL", now)
    new_pick = _kind_status_for_child(child["id"], "PICKUP", now)
    changed = (
        child.get("medical_authorization_status") != new_med
        or child.get("pickup_authorization_status") != new_pick
    )
    child["medical_authorization_status"] = new_med
    child["pickup_authorization_status"] = new_pick
    if persist and changed:
        touch(child)
    return child


def recount_emergency_contacts(child):
    """Recompute Child.emergency_contact_count from non-archived rows."""
    count = sum(
        1
        for ec in db.emergency_contacts.values()
        if ec["child_id"] == child["id"] and not ec.get("archived", False)
    )
    if child.get("emergency_contact_count") != count:
        child["emergency_contact_count"] = count
        touch(child)
    else:
        child["emergency_contact_count"] = count
    return child


def clock_advance_sweep():
    """On every clock advance: ACTIVE Authorization rows whose expires_at <= now → EXPIRED.

    Then re-project each affected child's medical/pickup status.
    """
    now = clock.now()
    affected_child_ids = set()
    for auth in db.authorizations.values():
        if auth["status"] != "ACTIVE":
            continue
        exp = parse_iso(auth["expires_at"])
        if now >= exp:
            auth["status"] = "EXPIRED"
            affected_child_ids.add(auth["child_id"])
    for cid in affected_child_ids:
        child = db.children.get(cid)
        if child:
            project_child_auth_statuses(child, persist=True)
