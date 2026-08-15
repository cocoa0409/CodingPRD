"""Ledger synchronization and cascades (PRD 2.10).

Recompute helpers mutate the parent's derived fields WITHOUT touching version —
the calling workflow decides the touch, so each logical operation bumps a parent
exactly once. Cascade helpers perform the full multi-entity side-effect chains.
"""
from db import db
from services.calculations import (
    compute_plan_coverage,
    engagement_hours,
    is_overdue,
    risk_tier,
    utilization,
)
from services.core import touch
from util import CLOCK


# ---------------------------------------------------------------------------
# Ledger recomputes (no touch inside — callers touch once per operation)
# ---------------------------------------------------------------------------

def recompute_engagement_hours(eng):
    """signed_off_workpaper_count, actual_hours, provisional_hours and both
    utilization variants (calculations 4 & 5)."""
    count, actual, provisional = engagement_hours(eng["id"])
    eng["signed_off_workpaper_count"] = count
    eng["actual_hours"] = float(actual)
    eng["provisional_hours"] = float(provisional)
    eng["utilization_final_pct"] = utilization(actual, eng["budget_hours"])
    eng["utilization_provisional_pct"] = utilization(provisional, eng["budget_hours"])


def recompute_engagement_reserved(eng):
    """Invariant: reserved_hours == sum of allocated_hours over ACTIVE assignments."""
    eng["reserved_hours"] = sum(
        a["allocated_hours"]
        for a in db["engagement_assignments"].values()
        if a["engagement_id"] == eng["id"] and a["status"] == "ACTIVE"
    )


def recompute_open_finding_count(eng):
    eng["open_finding_count"] = len([
        f for f in db["findings"].values()
        if f["engagement_id"] == eng["id"] and f["status"] != "FINAL"
    ])


def recompute_plan_aggregates(plan):
    """engagement_count (non-CANCELLED) + high_risk_coverage_pct (calculation 3)."""
    plan["engagement_count"] = len([
        e for e in db["engagements"].values()
        if e["audit_plan_id"] == plan["id"] and e["status"] != "CANCELLED"
    ])
    plan["high_risk_coverage_pct"] = compute_plan_coverage(plan["id"])


def recompute_finding_overdue(finding):
    """open_overdue_action_count vs the logical clock (calculation 7)."""
    finding["open_overdue_action_count"] = len([
        ap for ap in db["action_plans"].values()
        if ap["finding_id"] == finding["id"] and is_overdue(ap)
    ])


def sync_entity_risk_on_finalize(assessment):
    """Risk-assessment finalization ledger sync: entity.version always advances;
    current score/tier refresh only when this assessment's fiscal_year is the
    maximum FINALIZED fiscal_year for the entity."""
    entity = db["auditable_entities"].get(assessment["auditable_entity_id"])
    if entity is None:
        return
    finalized_years = [
        ra["fiscal_year"]
        for ra in db["risk_assessments"].values()
        if ra["auditable_entity_id"] == entity["id"] and ra["status"] == "FINALIZED"
    ]
    if finalized_years and assessment["fiscal_year"] == max(finalized_years):
        entity["current_inherent_risk_score"] = assessment["inherent_risk_score"]
        entity["current_risk_tier"] = risk_tier(assessment["inherent_risk_score"])
    touch(entity)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def cancel_engagement_cascade(eng):
    """Engagement cancel: ACTIVE assignments -> CANCELLED, reserved hours
    released, plan aggregates re-synced (PRD 3.4)."""
    eng["status"] = "CANCELLED"
    for a in db["engagement_assignments"].values():
        if a["engagement_id"] == eng["id"] and a["status"] == "ACTIVE":
            a["status"] = "CANCELLED"
            touch(a)
    recompute_engagement_reserved(eng)
    touch(eng)
    plan = db["audit_plans"].get(eng["audit_plan_id"])
    if plan is not None:
        recompute_plan_aggregates(plan)
        touch(plan)


def issue_report_cascade(report):
    """Report issuance (PRD 3.8): findings {AGREED, ESCALATED} -> FINAL with
    finalized_at; every workpaper of the engagement locked (tamper-evident
    freeze); engagement open_finding_count re-synced."""
    eng = db["engagements"].get(report["engagement_id"])
    if eng is None:
        return
    now = CLOCK.now_iso()
    for f in db["findings"].values():
        if f["engagement_id"] == eng["id"] and f["status"] in ("AGREED", "ESCALATED"):
            f["status"] = "FINAL"
            f["finalized_at"] = now
            touch(f)
    for wp in db["workpapers"].values():
        if wp["engagement_id"] == eng["id"] and not wp["locked"]:
            wp["locked"] = True
            touch(wp)
    recompute_open_finding_count(eng)
    touch(eng)


def qa_fail_cascade(eng):
    """QA FAIL regression (PRD 3.9), fired only while the engagement is REPORTING.

    L1: engagement REPORTING -> FIELDWORK, qa_regression_count += 1.
    L2: every SIGNED_OFF workpaper -> RETURNED (review_note QA_REOPEN,
        signed_off_at cleared); DRAFT/RETURNED/SUBMITTED untouched; rollups
        recomputed.
    L3: any PENDING_APPROVAL report of the engagement -> DRAFT.
    L4: every DRAFT committee pack of the engagement's plan -> is_stale_snapshot.
    """
    eng["status"] = "FIELDWORK"
    eng["qa_regression_count"] = eng.get("qa_regression_count", 0) + 1
    for wp in db["workpapers"].values():
        if wp["engagement_id"] == eng["id"] and wp["status"] == "SIGNED_OFF":
            wp["status"] = "RETURNED"
            wp["review_note"] = "QA_REOPEN"
            wp["signed_off_at"] = None
            touch(wp)
    recompute_engagement_hours(eng)
    touch(eng)
    for rep in db["audit_reports"].values():
        if rep["engagement_id"] == eng["id"] and rep["status"] == "PENDING_APPROVAL":
            rep["status"] = "DRAFT"
            touch(rep)
    for pack in db["committee_packs"].values():
        if pack["audit_plan_id"] == eng["audit_plan_id"] and pack["status"] == "DRAFT":
            if not pack["is_stale_snapshot"]:
                pack["is_stale_snapshot"] = True
            touch(pack)
