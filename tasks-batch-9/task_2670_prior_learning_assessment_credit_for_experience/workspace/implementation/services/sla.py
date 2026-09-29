"""Turnaround allowance, service-level posture and the escalation sweep (PRD 3.6)."""
from db import db, order_rows, portfolio_of_claim
from util import dtv, put_dt, rhu, touch

SLA_BASE_HOURS = {
    "CREDIT_BY_EXAM": 72,
    "PORTFOLIO": 240,
    "MILITARY_TRAINING": 96,
    "INDUSTRY_CREDENTIAL": 96,
}
EXPEDITED_BP = 5000
AT_RISK_BP = 8000
BREACH_BP = 10000


def artifact_multiplier_bp(claim):
    portfolio = portfolio_of_claim(claim["id"])
    if portfolio is None:
        return 10000
    count = portfolio["artifact_count"]
    if count <= 3:
        return 10000
    if count <= 8:
        return 12500
    return 15000


def turnaround_hours(claim):
    base = SLA_BASE_HOURS.get(claim["source_type"], 0)
    tiered = rhu(base * artifact_multiplier_bp(claim), 10000)
    if claim["priority_tier"] == "EXPEDITED":
        return rhu(tiered * EXPEDITED_BP, 10000)
    return tiered


def at_risk_offset_hours(sla_hours):
    return rhu(sla_hours * AT_RISK_BP, 10000)


def posture(assignment, now=None):
    """Returns (elapsed_bp, sla_state) against the logical clock."""
    if now is None:
        now = db.clock
    assigned_at = dtv(assignment, "assigned_at")
    sla_hours = assignment["sla_hours"]
    if assigned_at is None or not sla_hours:
        return 0, "ON_TRACK"
    elapsed_ms = int((now - assigned_at).total_seconds() * 1000)
    elapsed_bp = rhu(elapsed_ms * 10000, sla_hours * 3600000)
    if elapsed_bp >= BREACH_BP:
        state = "BREACHED"
    elif elapsed_bp >= AT_RISK_BP:
        state = "AT_RISK"
    else:
        state = "ON_TRACK"
    return elapsed_bp, state


LIVE_STATUSES = ("ASSIGNED", "ACCEPTED")


def refresh_posture(assignment):
    """Live assignments recompute; terminal ones keep their last computed posture."""
    if assignment["status"] in LIVE_STATUSES:
        elapsed_bp, state = posture(assignment)
        assignment["elapsed_bp"] = elapsed_bp
        assignment["sla_state"] = state
    return assignment["elapsed_bp"], assignment["sla_state"]


def freeze_posture(assignment):
    elapsed_bp, state = posture(assignment)
    assignment["elapsed_bp"] = elapsed_bp
    assignment["sla_state"] = state


def revoke_assignment(assignment, reason):
    assessor = db.assessors.get(assignment["assessor_id"])
    freeze_posture(assignment)
    assignment["status"] = "REVOKED"
    assignment["revoke_reason"] = reason
    touch(assignment)
    if assessor is not None:
        assessor["active_assignment_count"] = max(0, assessor["active_assignment_count"] - 1)
        touch(assessor)


def revoke_open_assignments(claim, reason):
    revoked = []
    for assignment in db.assignments.values():
        if assignment["claim_id"] == claim["id"] and assignment["status"] in LIVE_STATUSES:
            revoke_assignment(assignment, reason)
            revoked.append(assignment)
    return revoked


def run_escalation_sweep():
    from services import invoice as invoice_service
    from services import selection as selection_service

    candidates = [a for a in db.assignments.values() if a["status"] in LIVE_STATUSES]
    candidates = order_rows(candidates, [
        (lambda r: dtv(r, "due_at"), False),
        (lambda r: r["created_at"], False),
    ])
    evaluated = len(candidates)
    at_risk = 0
    breached = []
    for assignment in candidates:
        elapsed_bp, state = posture(assignment)
        assignment["elapsed_bp"] = elapsed_bp
        assignment["sla_state"] = state
        if state == "BREACHED":
            breached.append(assignment)
        elif state == "AT_RISK":
            at_risk += 1

    revoked_ids = []
    replacement_ids = []
    credited_invoice_ids = []
    for assignment in breached:
        claim = db.claims.get(assignment["claim_id"])
        # hop one
        revoke_assignment(assignment, "SLA_BREACH")
        revoked_ids.append(assignment["id"])
        if claim is None:
            continue
        # hop two
        claim["sla_breach_count"] += 1
        claim["priority_tier"] = "EXPEDITED"
        touch(claim)
        # hop three
        student = db.students.get(claim["student_id"])
        priced = invoice_service.recompute(claim, student)
        if priced is not None:
            credited_invoice_ids.append(priced["id"])
        # hop four
        replacement = selection_service.create_replacement(claim)
        if replacement is not None:
            replacement_ids.append(replacement["id"])

    return {
        "evaluated_count": evaluated,
        "at_risk_count": at_risk,
        "breached_count": len(breached),
        "revoked_assignment_ids": revoked_ids,
        "replacement_assignment_ids": replacement_ids,
        "credited_invoice_ids": credited_invoice_ids,
    }
