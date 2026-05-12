"""Defect lifecycle business logic: scoring/SLA recompute and reopen cascade."""

from __future__ import annotations

import db
from config import (
    DEFECT_REOPENED, DEFECT_VERIFIED, OUTCOME_PASSED, OUTCOME_FAILED,
)
from services.audit import append_audit
from services.calculations import compute_effective_sla, compute_priority_score


def recompute_score_and_due(defect: dict, *, project_clock: int) -> dict:
    """Recompute priority_score, response_due_minute, resolution_due_minute.
    Called on defect create, override approve, reopen, and clock-driven sweeps.
    """
    score = compute_priority_score(
        effective_severity=defect["effective_severity"],
        business_impact=defect["business_impact"],
        reopen_count=defect.get("reopen_count", 0),
        current_clock_minute=project_clock,
        report_clock_minute=defect["report_clock_minute"],
    )
    effective_resp, effective_res = compute_effective_sla(
        defect["effective_severity"], score,
    )
    defect["priority_score"] = score
    defect["response_due_minute"] = defect["report_clock_minute"] + effective_resp
    defect["resolution_due_minute"] = defect["report_clock_minute"] + effective_res
    return defect


def reopen_cascade(defect: dict, project: dict, actor_id: str):
    """Apply the verification-failure reopen cascade (5 linked side effects).
    Mutates `defect` in place and appends audit entries.
    Caller is expected to commit defect via db.update and bump version.
    """
    prior_escalation = defect.get("escalation_level", 0)
    prior_status = defect["status"]
    # Link 1: increment reopen_count
    defect["reopen_count"] = defect.get("reopen_count", 0) + 1
    # Link 2: recompute priority_score using new reopen_count (age vs current clock)
    new_score = compute_priority_score(
        effective_severity=defect["effective_severity"],
        business_impact=defect["business_impact"],
        reopen_count=defect["reopen_count"],
        current_clock_minute=project["clock_minute"],
        report_clock_minute=defect["report_clock_minute"],
    )
    defect["priority_score"] = new_score
    # Link 3: reset response_due_minute = current_clock + effective_response
    effective_resp, _ = compute_effective_sla(
        defect["effective_severity"], new_score,
    )
    defect["response_due_minute"] = project["clock_minute"] + effective_resp
    # Update status to REOPENED
    defect["status"] = DEFECT_REOPENED
    # Reset escalation_level to 0
    defect["escalation_level"] = 0
    # Link 4: status change audit
    append_audit(
        defect_id=defect["id"],
        event_type="STATUS_CHANGE",
        actor_id=actor_id,
        from_value=prior_status,
        to_value=DEFECT_REOPENED,
        at_minute=project["clock_minute"],
    )
    # Link 5: escalation reset audit
    append_audit(
        defect_id=defect["id"],
        event_type="ESCALATION",
        actor_id=actor_id,
        from_value=str(prior_escalation),
        to_value="0",
        at_minute=project["clock_minute"],
    )


def commit_defect(defect: dict):
    """Persist defect mutations and bump version/updated_at."""
    return db.update("defects", defect["id"], defect, bump=True)
