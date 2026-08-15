"""Cascade / recompute helpers shared by route handlers (PRD §2.4, §3).

BusinessOwner counters (active_assessment_count, open_escalation_count,
assignment_suspended), Control freshness (effectiveness_factor,
next_review_due), TrainingRollout roll-ups (assigned_count, completed_count,
completion_pct, past_due) and EvidencePackage.artifact_count are computed on
read in serializers.py; this module owns the *stored* derived state:
GapAnalysis.covered_points / residual_gap_points (frozen at CONFIRMED) and
ImplementationPlan.deadline_posture (frozen at COMPLETED/VERIFIED).
"""

from db import new_id, now_clock, store, touch
from services.calculations import compute_gap_scores, posture_for

# Non-terminal plan states (terminal: VERIFIED)
PLAN_NON_TERMINAL = ("DRAFT", "SUBMITTED", "REJECTED", "APPROVED",
                     "IN_EXECUTION", "COMPLETED")


# ---------------------------------------------------------------------------
# Gap score recompute (live while OPEN / IN_REVIEW)
# ---------------------------------------------------------------------------


def recompute_gap(gap):
    clock = now_clock()
    covered, residual = compute_gap_scores(
        gap, store.mappings.values(), store.controls, clock)
    gap["covered_points"] = covered
    gap["residual_gap_points"] = residual
    touch(gap)


def recompute_open_gaps_for_obligation(obligation_id):
    for gap in store.gap_analyses.values():
        if gap["obligation_id"] == obligation_id and gap["status"] in ("OPEN", "IN_REVIEW"):
            recompute_gap(gap)


def recompute_open_gaps_for_control(control_id):
    """Gaps whose obligation has an APPROVED mapping to this control."""
    obligation_ids = {
        m["obligation_id"]
        for m in store.mappings.values()
        if m["control_id"] == control_id and m["status"] == "APPROVED"
    }
    for oid in obligation_ids:
        recompute_open_gaps_for_obligation(oid)


def recompute_all_open_gaps():
    for gap in store.gap_analyses.values():
        if gap["status"] in ("OPEN", "IN_REVIEW"):
            recompute_gap(gap)


# ---------------------------------------------------------------------------
# Escalations
# ---------------------------------------------------------------------------


def has_open_escalation(target_id):
    return any(
        e["target_id"] == target_id and e["status"] in ("OPEN", "ACKNOWLEDGED")
        for e in store.escalations.values()
    )


def create_escalation(target_type, target_id, trigger_rule, business_owner_id):
    escalation = {
        "id": new_id(),
        "target_type": target_type,
        "target_id": target_id,
        "trigger_rule": trigger_rule,
        "business_owner_id": business_owner_id,
        "level": 1,
        "status": "OPEN",
        "resolution_code": None,
        "opened_at": now_clock(),
        "resolved_at": None,
    }
    from db import stamp_new
    stamp_new(escalation)
    store.escalations[escalation["id"]] = escalation
    return escalation


# ---------------------------------------------------------------------------
# Deadline posture recompute (plans in APPROVED / IN_EXECUTION)
# ---------------------------------------------------------------------------


def recompute_plan_posture(plan):
    """Recompute one plan's deadline_posture; spawns DEADLINE_BREACH
    escalation when crossing into OVERDUE with none open."""
    if plan["execution_status"] not in ("APPROVED", "IN_EXECUTION"):
        return
    new_posture = posture_for(plan["target_completion_date"], now_clock())
    if new_posture == plan["deadline_posture"]:
        return
    became_overdue = new_posture == "OVERDUE" and plan["deadline_posture"] != "OVERDUE"
    plan["deadline_posture"] = new_posture
    touch(plan)
    if became_overdue and not has_open_escalation(plan["id"]):
        create_escalation("IMPLEMENTATION_PLAN", plan["id"], "DEADLINE_BREACH",
                          plan["business_owner_id"])


def recompute_all_postures():
    for plan in list(store.plans.values()):
        recompute_plan_posture(plan)


# ---------------------------------------------------------------------------
# RegulatoryChange closure (bubble-up on EvidencePackage seal)
# ---------------------------------------------------------------------------


def reevaluate_change_closure(change_id):
    """TRIAGED_APPLICABLE -> CLOSED when every ACTIVE obligation of the change
    has >= 1 plan and none of those obligations' plans is non-terminal."""
    change = store.regulatory_changes.get(change_id)
    if change is None or change["status"] != "TRIAGED_APPLICABLE":
        return
    active_obligations = [
        o for o in store.obligations.values()
        if o["regulatory_change_id"] == change_id and o["status"] == "ACTIVE"
    ]
    for ob in active_obligations:
        plans = [p for p in store.plans.values() if p["obligation_id"] == ob["id"]]
        if not plans:
            return
        if any(p["execution_status"] in PLAN_NON_TERMINAL for p in plans):
            return
    change["status"] = "CLOSED"
    touch(change)
