"""Version bookkeeping, the posture ladder and its cascades.

A row advances its version by exactly one per request no matter how many
side effects touch it (PRD section 2.4: version increases by exactly 1 on
every mutation of that row).
"""

from flask import g

import calc
import derive
from db import db


def touched_set():
    if not hasattr(g, "touched"):
        g.touched = set()
    return g.touched


def touch(row):
    """Mutate a row's audit fields once per request."""
    if row is None:
        return
    seen = touched_set()
    if row["id"] in seen:
        return
    seen.add(row["id"])
    row["version"] = row["version"] + 1
    row["updated_at"] = db.clock


def suspend_if_needed(account):
    if account["dr_enrollment_state"] == "SUSPENDED":
        return
    if derive.dr_optout_count(account["id"]) >= calc.DR_OPTOUT_SUSPEND_COUNT:
        account["dr_enrollment_state"] = "SUSPENDED"
        touch(account)


def optout_notified_events(store):
    """Food-safety abandonment: NOTIFIED events of the store's accounts opt out."""
    count = 0
    for account in derive.store_accounts(store["id"]):
        changed = False
        for event in derive.account_events(account["id"]):
            if event["event_state"] == "NOTIFIED":
                event["event_state"] = "OPTED_OUT"
                event["opt_out_reason"] = "FOOD_SAFETY_POSTURE"
                touch(event)
                count += 1
                changed = True
        if changed:
            touch(account)
            suspend_if_needed(account)
    return count


def revoke_schedule_extend_overrides(store):
    """Posture cascade: ACTIVE SCHEDULE_EXTEND overrides are revoked by the system."""
    count = 0
    for override in derive.store_overrides(store["id"]):
        if override["state"] == "ACTIVE" and override["override_type"] == "SCHEDULE_EXTEND":
            override["state"] = "REVOKED"
            override["revoke_source"] = "SYSTEM_POSTURE"
            override["revoked_by_user_id"] = None
            touch(override)
            count += 1
    if count:
        touch(store)
    return count


def escalate_proposed_retrofits(store):
    count = 0
    for project in derive.store_retrofits(store["id"]):
        if project["state"] == "PROPOSED" and not project["escalated_review"]:
            project["escalated_review"] = True
            touch(project)
            count += 1
    return count


def recompute_posture(store):
    """Recompute the ladder and run the consequences of a posture raise."""
    result = {
        "dr_events_opted_out": 0,
        "overrides_revoked": 0,
        "escalated_retrofit_count": 0,
        "posture_changed": False,
    }
    if store is None:
        return result
    old = store["energy_posture"]
    new = calc.compute_posture(store)
    if new == old:
        return result
    store["energy_posture"] = new
    touch(store)
    result["posture_changed"] = True
    if calc.POSTURE_RANK[new] > calc.POSTURE_RANK[old]:
        if new == "LOCKED":
            result["dr_events_opted_out"] = optout_notified_events(store)
        result["overrides_revoked"] = revoke_schedule_extend_overrides(store)
        if new in ("CONSTRAINED", "LOCKED"):
            result["escalated_retrofit_count"] = escalate_proposed_retrofits(store)
    return result
