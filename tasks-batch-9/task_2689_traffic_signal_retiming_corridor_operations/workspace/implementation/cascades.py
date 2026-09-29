"""Multi-aggregate cascades (PRD sections 2.11, 3.8, 3.10).

Each cascade is applied inside the triggering request, in the order the PRD
pins, and every touched row has updated_at refreshed and version incremented by
exactly 1.  Guards are checked by the caller before any write happens, so a
failing link leaves nothing behind.
"""

import calc
import clock
import derive
from db import db, touch

PLAN_STATUSES_SUPERSEDED_BY_ABANDON = ("DRAFT", "COORDINATED", "SUBMITTED", "CERTIFIED")


# ---- plan compensation ----------------------------------------------------

def compensate_plan(plan):
    """Undo every write the coordination pipeline made to one plan.

    Shared by SUBMITTED -> DRAFT (return) and DEPLOYED -> DRAFT (fine tuning).
    The caller sets the new status and bumps the plan's version.
    """
    plan["cycle_length_sec"] = plan["drafted_cycle_length_sec"]
    for split in derive.splits_of_plan(plan["id"]):
        split["effective_split_sec"] = split["split_sec"]
    plan["offset_sec"] = 0
    plan["ped_compliance_state"] = "PENDING"
    plan["effective_split_total_sec"] = plan["drafted_split_total_sec"]
    for check in derive.checks_of_plan(plan["id"]):
        db.ped_checks.pop(check["id"], None)
    return plan


# ---- implementation cascade (5 links) ------------------------------------

def implementation_cascade(project):
    corridor_id = project["corridor_id"]

    # LINK 1 -- the project itself.
    project["status"] = "IMPLEMENTED"
    touch(project)

    # LINK 2 -- every CERTIFIED plan deploys, in corridor-sequence then
    # tod_start_min order.
    certified = [p for p in derive.plans_of_project(project["id"]) if p["status"] == "CERTIFIED"]

    def order_key(plan):
        seq = derive.sequence_index_of(corridor_id, plan["intersection_id"])
        return (seq if seq is not None else 10 ** 9, plan["tod_start_min"], plan["_seq"])

    certified.sort(key=order_key)

    now = clock.now()
    touched_intersections = []
    for plan in certified:
        plan["status"] = "DEPLOYED"
        touch(plan)

        # LINK 3(i) -- supersede the older deployed plan for the same label.
        for other in db.plans.values():
            if other["id"] == plan["id"]:
                continue
            if other["intersection_id"] != plan["intersection_id"]:
                continue
            if other["tod_period"] != plan["tod_period"]:
                continue
            if other["status"] != "DEPLOYED":
                continue
            if other["created_at"] < plan["created_at"] or (
                other["created_at"] == plan["created_at"] and other["_seq"] < plan["_seq"]
            ):
                other["status"] = "SUPERSEDED"
                touch(other)

        # LINK 3(ii) -- refresh the intersection.
        intersection = db.intersections.get(plan["intersection_id"])
        if intersection is not None and intersection["id"] not in touched_intersections:
            touched_intersections.append(intersection["id"])

    for intersection_id in touched_intersections:
        intersection = db.intersections[intersection_id]
        intersection["last_retimed_at"] = now
        touch(intersection)

    # LINK 4 -- every corridor holding a member for a touched intersection.
    affected = []
    for corridor in db.corridors.values():
        for member in derive.members_of(corridor["id"]):
            if member["intersection_id"] in touched_intersections:
                affected.append(corridor)
                break
    affected.sort(key=lambda c: (c["created_at"], c["_seq"]))

    for corridor in affected:
        derive.recompute_corridor_score(corridor, screening=False)
        deferred = False
        if (
            corridor["priority_score"] < calc.DEFER_SCORE_THRESHOLD
            and corridor["selection_status"] == "SCREENED"
        ):
            corridor["selection_status"] = "DEFERRED"
            deferred = True
        touch(corridor)
        if deferred:
            # LINK 5 -- requeue the corridor's TRIAGED coordination complaints.
            requeue_coordination_complaints(corridor["id"])

    return project


def requeue_coordination_complaints(corridor_id):
    rows = [
        c
        for c in derive.complaints_of_corridor(corridor_id)
        if c["status"] == "TRIAGED" and c["category"] == "COORDINATION"
    ]
    rows.sort(key=lambda c: (c["created_at"], c["_seq"]))
    for complaint in rows:
        complaint["status"] = "OPEN"
        complaint["reopen_count"] = complaint["reopen_count"] + 1
        touch(complaint)
    return rows


# ---- fine-tuning cascade (links 2..4) ------------------------------------

def find_reopen_target(intersection_id, tod_period):
    candidates = [
        p
        for p in db.plans.values()
        if p["intersection_id"] == intersection_id
        and p["tod_period"] == tod_period
        and p["status"] == "DEPLOYED"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return candidates[-1]


def fine_tuning_cascade(project, intersection_id, tod_period):
    """Links 2, 3 and 4.  Returns True when the project looped back."""
    plan = find_reopen_target(intersection_id, tod_period)
    if plan is None:
        return False

    # LINK 2 -- the deployed plan reopens as a draft.
    compensate_plan(plan)
    plan["status"] = "DRAFT"
    touch(plan)

    # LINK 3 -- the project loops back into plan development.
    project["status"] = "PLAN_DEVELOPMENT"
    project["tuning_round"] = project["tuning_round"] + 1
    touch(project)

    # LINK 4 -- provisional evaluations are invalidated.
    provisional = [
        e for e in derive.evaluations_of_project(project["id"]) if e["status"] == "PROVISIONAL"
    ]
    provisional.sort(key=lambda e: (e["created_at"], e["_seq"]))
    for evaluation in provisional:
        evaluation["status"] = "INVALIDATED"
        touch(evaluation)
    return True


# ---- project disposition cascades ----------------------------------------

def close_cascade(project):
    """EVALUATION -> CLOSED: linked complaints are resolved."""
    project["status"] = "CLOSED"
    touch(project)
    rows = [
        c
        for c in db.complaints.values()
        if c.get("linked_project_id") == project["id"] and c["status"] == "LINKED"
    ]
    rows.sort(key=lambda c: (c["created_at"], c["_seq"]))
    for complaint in rows:
        complaint["status"] = "RESOLVED"
        touch(complaint)
    return project


def abandon_cascade(project):
    """DATA_COLLECTION|PLAN_DEVELOPMENT -> ABANDONED."""
    project["status"] = "ABANDONED"
    touch(project)

    plans = [
        p
        for p in derive.plans_of_project(project["id"])
        if p["status"] in PLAN_STATUSES_SUPERSEDED_BY_ABANDON
    ]
    plans.sort(key=lambda p: (p["created_at"], p["_seq"]))
    for plan in plans:
        plan["status"] = "SUPERSEDED"
        touch(plan)

    rows = [
        c
        for c in db.complaints.values()
        if c.get("linked_project_id") == project["id"] and c["status"] == "LINKED"
    ]
    rows.sort(key=lambda c: (c["created_at"], c["_seq"]))
    for complaint in rows:
        complaint["status"] = "OPEN"
        complaint["linked_project_id"] = None
        complaint["reopen_count"] = complaint["reopen_count"] + 1
        touch(complaint)
    return project
