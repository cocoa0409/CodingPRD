"""Termination, reassignment and reinstatement cascades (PRD section 3.8)."""

from common import clock_str, touch
from db import db
from services import planlib
from services.commission import statements_of_run
from services.genealogy import (
    children_of,
    recompute_direct_downline_count,
    recompute_subtree_paths,
)
from services.qual import recompute_live_group_fields


def approved_run_blocks_termination(consultant):
    for run in db.runs.values():
        if run["status"] != "APPROVED":
            continue
        for statement in statements_of_run(run["id"]):
            if statement["consultant_id"] == consultant["id"] and statement["status"] == "ACTIVE":
                return True
    return False


def terminate(consultant, reason, from_sanction=False):
    plan = db.plans.get(consultant["compensation_plan_id"])
    old_sponsor_id = consultant.get("sponsor_consultant_id")

    consultant["status"] = "TERMINATED"
    consultant["terminated_at"] = clock_str()
    consultant["termination_reason"] = reason
    if from_sanction:
        consultant["active_sanction_level"] = "TERMINATION"
        consultant["active_sanction_until"] = None
    touch(consultant)

    moved = []
    for child in children_of(consultant["id"]):
        if child["status"] == "TERMINATED":
            continue
        child["sponsor_consultant_id"] = old_sponsor_id
        child["reassigned_from_sponsor_consultant_id"] = consultant["id"]
        child["reassignment_count"] = int(child["reassignment_count"]) + 1
        touch(child)
        moved.append(child)

    for child in moved:
        recompute_subtree_paths(child["id"])

    recompute_direct_downline_count(consultant["id"])
    if old_sponsor_id is not None:
        recompute_direct_downline_count(old_sponsor_id)

    recompute_live_group_fields()

    if plan is not None:
        plan["consultant_count"] = max(0, int(plan["consultant_count"]) - 1)
        touch(plan)


def nearest_non_terminated_ancestor(consultant_id):
    """Walk up from the given consultant's sponsor chain for a live sponsor."""
    node = db.consultants.get(consultant_id)
    if node is None:
        return None
    current_id = node.get("sponsor_consultant_id")
    seen = set()
    while current_id is not None and current_id not in seen:
        seen.add(current_id)
        current = db.consultants.get(current_id)
        if current is None:
            return None
        if current["status"] != "TERMINATED":
            return current["id"]
        current_id = current.get("sponsor_consultant_id")
    return None


def reinstate(consultant):
    plan = db.plans.get(consultant["compensation_plan_id"])

    restored_sponsor_id = None
    previous_id = consultant.get("reassigned_from_sponsor_consultant_id")
    if previous_id is not None:
        previous = db.consultants.get(previous_id)
        if previous is not None and previous["status"] != "TERMINATED":
            restored_sponsor_id = previous["id"]
        else:
            restored_sponsor_id = nearest_non_terminated_ancestor(previous_id)

    consultant["status"] = "ACTIVE"
    consultant["reinstated_at"] = clock_str()
    consultant["reinstatement_count"] = int(consultant["reinstatement_count"]) + 1
    consultant["sponsor_consultant_id"] = restored_sponsor_id
    base = planlib.base_rung(plan) if plan else None
    if base is not None:
        consultant["rank_code"] = base["rank_code"]
        consultant["rank_order"] = base["rank_order"]
    consultant["rank_source"] = "REINSTATEMENT"
    consultant["consecutive_qualified_count"] = 0
    consultant["grace_periods_used"] = 0
    consultant["active_sanction_level"] = None
    consultant["active_sanction_until"] = None
    touch(consultant)

    recompute_subtree_paths(consultant["id"], bump_self=False)

    if restored_sponsor_id is not None:
        sponsor = db.consultants.get(restored_sponsor_id)
        if sponsor is not None:
            sponsor["direct_downline_count"] = int(sponsor["direct_downline_count"]) + 1
            touch(sponsor)

    recompute_direct_downline_count(consultant["id"])
    recompute_live_group_fields()

    if plan is not None:
        plan["consultant_count"] = int(plan["consultant_count"]) + 1
        touch(plan)
