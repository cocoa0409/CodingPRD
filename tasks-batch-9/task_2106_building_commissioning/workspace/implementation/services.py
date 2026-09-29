"""Cross-aggregate cascades and roll-up reconciliation (PRD 2.6 - 2.8)."""
from core import (
    D, bump_project, clock, db, new_row, num, rhu, sorted_rows, touch, touch_updated,
)
import calc


# ---------------------------------------------------------------------------
# Equipment verification dimension
# ---------------------------------------------------------------------------
def demote_equipment(equipment_row):
    """Drive the verification dimension back to UNVERIFIED."""
    if equipment_row["verification_status"] in calc.VERIFIED_SET:
        equipment_row["verification_status"] = "UNVERIFIED"
        touch(equipment_row)
        return True
    return False


def promote_equipment(equipment_row):
    if (equipment_row["verification_status"] == "UNVERIFIED"
            and equipment_row["blocking_issue_count"] == 0
            and calc.checklist_is_verified(equipment_row["id"])):
        equipment_row["verification_status"] = "PREFUNCTIONAL_VERIFIED"
        touch(equipment_row)
        return True
    return False


def recompute_blocking_issue_count(equipment_row):
    count = 0
    for issue in db.issues.values():
        if (issue.get("equipment_id") == equipment_row["id"]
                and issue["blocks_acceptance"]
                and issue["status"] in calc.LIVE_ISSUE_STATUSES):
            count += 1
    if count != equipment_row["blocking_issue_count"]:
        equipment_row["blocking_issue_count"] = count
        touch(equipment_row)
    return count


def cancel_scheduled_tests(equipment_id, statuses):
    for test in calc.equipment_tests(equipment_id):
        if test["status"] in statuses:
            test["status"] = "CANCELLED"
            touch(test)


# ---------------------------------------------------------------------------
# Issue lifecycle helpers
# ---------------------------------------------------------------------------
def create_issue(project, origin, severity, description, equipment_id, source_ref_id,
                 opened_by_user_id):
    equipment_row = db.equipment.get(equipment_id) if equipment_id else None
    hold = calc.compute_retainage_hold_cents(project, equipment_row, severity)
    issue = new_row(db.issues, {
        "project_id": project["id"],
        "equipment_id": equipment_id,
        "closure_retest_id": None,
        "origin": origin,
        "source_ref_id": source_ref_id,
        "severity": severity,
        "description": description,
        "status": "OPEN",
        "blocks_acceptance": severity in ("S1", "S2"),
        "opened_at": clock.now_iso(),
        "opened_by_user_id": opened_by_user_id,
        "proposed_by_user_id": None,
        "proposed_resolution": None,
        "retainage_hold_cents": hold,
        "reopen_count": 0,
    })
    if issue["blocks_acceptance"] and equipment_row is not None:
        recompute_blocking_issue_count(equipment_row)
        demote_equipment(equipment_row)
    return issue


def apply_issue_status_change(issue, new_status):
    """Move an issue and run the blocking-count / equipment demotion+promotion rules."""
    old_status = issue["status"]
    was_live = old_status in calc.LIVE_ISSUE_STATUSES
    issue["status"] = new_status
    now_live = new_status in calc.LIVE_ISSUE_STATUSES
    equipment_row = db.equipment.get(issue.get("equipment_id")) if issue.get("equipment_id") else None
    if issue["blocks_acceptance"] and equipment_row is not None and was_live != now_live:
        count = recompute_blocking_issue_count(equipment_row)
        if now_live:
            demote_equipment(equipment_row)
        elif count == 0:
            promote_equipment(equipment_row)


# ---------------------------------------------------------------------------
# Posture
# ---------------------------------------------------------------------------
def apply_posture(project):
    """Recompute the severity index and re-derive the posture (PRD 2.6)."""
    index = calc.compute_issue_severity_index(project["id"])
    old_index = D(str(project["issue_severity_index"]))
    if index != old_index:
        project["issue_severity_index"] = num(index)
        touch_updated(project)
    posture = calc.derive_posture(index)
    old_posture = project["readiness_posture"]
    if posture == old_posture:
        return
    project["readiness_posture"] = posture
    if posture == "FROZEN":
        for row in calc.project_deferred_tests(project["id"]):
            if row["status"] == "PLANNED":
                row["status"] = "BLOCKED"
                touch(row)
    elif old_posture == "FROZEN":
        for row in calc.project_deferred_tests(project["id"]):
            if row["status"] == "BLOCKED":
                row["status"] = "PLANNED"
                touch(row)
    bump_project(project)


# ---------------------------------------------------------------------------
# Credit documentation score
# ---------------------------------------------------------------------------
def recompute_credit(credit):
    rows = calc.credit_evidence(credit["id"])
    evidence_count = len(rows)
    fresh_count = sum(1 for r in rows if not r["is_stale"])
    stale_count = sum(1 for r in rows if r["is_stale"])
    completeness, provisional_tier, score, final_tier = calc.compute_documentation_score(
        credit["required_evidence_count"], fresh_count, stale_count,
    )
    changed = False
    updates = {
        "evidence_count": evidence_count,
        "fresh_evidence_count": fresh_count,
        "stale_evidence_count": stale_count,
        "completeness_ratio": num(completeness),
        "provisional_tier": provisional_tier,
        "documentation_score": num(score),
        "final_tier": final_tier,
    }
    for key, value in updates.items():
        if credit.get(key) != value:
            credit[key] = value
            changed = True
    if changed:
        touch(credit)
    if credit["status"] == "SUBMITTED" and final_tier == "NONE":
        credit["status"] = "WITHDRAWN"
        touch(credit)
        project = db.projects.get(credit["project_id"])
        if project is not None:
            project["withdrawn_credit_count"] = project.get("withdrawn_credit_count", 0) + 1
            touch_updated(project)


def sync_evidence_freshness():
    for row in sorted_rows(list(db.evidence.values())):
        stale = calc.evidence_is_stale(row)
        if stale != row["is_stale"]:
            row["is_stale"] = stale
            if stale:
                row["staled_at"] = clock.now_iso()
            touch(row)


# ---------------------------------------------------------------------------
# Project roll-ups
# ---------------------------------------------------------------------------
def recompute_project_rollups(project):
    pid = project["id"]
    changed = False

    retainage = calc.compute_retainage_withheld(pid)
    if project["retainage_withheld_cents"] != retainage:
        project["retainage_withheld_cents"] = retainage
        changed = True

    open_blocking = sum(
        1 for i in calc.project_issues(pid)
        if i["status"] in calc.LIVE_ISSUE_STATUSES and i["blocks_acceptance"]
    )
    if project["open_blocking_issue_count"] != open_blocking:
        project["open_blocking_issue_count"] = open_blocking
        changed = True

    verified_units = 0
    for eq in calc.project_equipment(pid):
        if calc.checklist_is_verified(eq["id"]):
            verified_units += eq["weight_units"]
    if project["verified_prefunctional_units"] != verified_units:
        project["verified_prefunctional_units"] = verified_units
        changed = True

    score = num(calc.compute_acceptance_score(pid, "PROVISIONAL"))
    if project["acceptance_completion_score"] != score:
        project["acceptance_completion_score"] = score
        changed = True

    awarded = D(0)
    for credit in db.credits.values():
        if credit["project_id"] == pid and credit["status"] == "AWARDED":
            awarded += D(str(credit["awarded_points"]))
    awarded = num(rhu(awarded, 2))
    if project["total_awarded_points"] != awarded:
        project["total_awarded_points"] = awarded
        changed = True

    if changed:
        touch_updated(project)


def reconcile():
    """Immediate reconciliation of every derived figure (PRD 2.8)."""
    for eq in db.equipment.values():
        recompute_blocking_issue_count(eq)
    sync_evidence_freshness()
    for credit in sorted_rows(list(db.credits.values())):
        recompute_credit(credit)
    for project in sorted_rows(list(db.projects.values())):
        recompute_project_rollups(project)
        apply_posture(project)
