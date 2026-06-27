"""Unit-posture reconciliation + clock-advance sweeps (PRD §2.4, §2.5, §3.5).

Derived Unit fields (operating_status, monitoring_health, warranty_status,
compliance_score, last_exercise_at, runtime_hours, next_due_at, etc.) are never
written directly by clients. They are recomputed here. Each reconciliation that
actually changes a unit refreshes updated_at and bumps version.
"""
from datetime import timedelta

import calc
import db
from clock import get_now, to_iso8601
from timeutil import (
    add_months, parse, whole_days_between, whole_months_between,
)


# ---------------------------------------------------------------------------
# Plan due-date helpers
# ---------------------------------------------------------------------------
def plan_period_months(plan):
    return 12 if plan["frequency"] == "ANNUAL" else 6


def recompute_plan_due(plan):
    """next_due_at = plan anchor + (visits_completed_ytd + 1) * period.

    Anchor is the plan's creation instant. Frozen while SUSPENDED (left as-is).
    """
    if plan["status"] != "ACTIVE":
        return
    anchor = parse(plan["created_at"])
    months = plan_period_months(plan) * (plan["visits_completed_ytd"] + 1)
    plan["next_due_at"] = to_iso8601(add_months(anchor, months))


# ---------------------------------------------------------------------------
# Compliance + monitoring
# ---------------------------------------------------------------------------
def recompute_compliance(unit):
    now = get_now()
    ws = parse(unit["warranty_start"])
    if ws is None:
        unit["compliance_score"] = 100
        return
    days_active = whole_days_between(ws, now)
    completed = 0
    last_success = None
    for log in db.exercise_logs.values():
        if log["unit_id"] != unit["id"]:
            continue
        occ = parse(log["occurred_at"])
        if log["result"] == "SUCCESS" and occ is not None and occ <= now:
            completed += 1
            if last_success is None or occ > last_success:
                last_success = occ
    unit["compliance_score"] = calc.run_compliance_score(days_active, completed)
    unit["last_exercise_at"] = to_iso8601(last_success) if last_success else None


def recompute_monitoring(unit):
    """Parallel monitoring_health axis, driven by the §3.5 transition graph.

    Transitions (threshold 70, inclusive on the >= side):
      OFFLINE -> OK        when monitoring enabled and score >= 70
      OK -> DEGRADED       when score < 70 (monitoring still enabled)
      DEGRADED -> OK       when score >= 70
      OK/DEGRADED -> OFFLINE  when monitoring disabled or unit NON_COMPLIANT
    There is no OFFLINE -> DEGRADED edge: a freshly-enabled unit with a low score
    stays OFFLINE until its score first reaches 70.
    """
    if unit["operating_status"] == "NON_COMPLIANT" or not unit["monitoring_enabled"]:
        unit["monitoring_health"] = "OFFLINE"
        return
    score = unit["compliance_score"]
    current = unit["monitoring_health"]
    healthy = score >= calc.HEALTH_THRESHOLD
    if current == "OFFLINE":
        if healthy:
            unit["monitoring_health"] = "OK"
        # else: stay OFFLINE (no OFFLINE->DEGRADED edge)
    elif current == "OK":
        unit["monitoring_health"] = "OK" if healthy else "DEGRADED"
    elif current == "DEGRADED":
        unit["monitoring_health"] = "OK" if healthy else "DEGRADED"


# ---------------------------------------------------------------------------
# Recall posture
# ---------------------------------------------------------------------------
def unit_has_overdue_mandatory(unit_id):
    for rem in db.recall_remediations.values():
        if rem["unit_id"] != unit_id:
            continue
        if rem["status"] != "OVERDUE":
            continue
        campaign = db.recall_campaigns.get(rem["campaign_id"])
        if campaign and campaign["severity"] == "MANDATORY":
            return True
    return False


# ---------------------------------------------------------------------------
# Warranty status
# ---------------------------------------------------------------------------
def within_warranty_window(unit):
    ws = parse(unit["warranty_start"])
    if ws is None:
        return False
    expiry = add_months(ws, unit["warranty_total_months"])
    return get_now() < expiry


# ---------------------------------------------------------------------------
# Maintenance posture (SERVICE_DUE)
# ---------------------------------------------------------------------------
def has_due_active_plan(unit_id):
    now = get_now()
    for plan in db.maintenance_plans.values():
        if plan["unit_id"] != unit_id or plan["status"] != "ACTIVE":
            continue
        nd = parse(plan["next_due_at"])
        if nd is not None and nd <= now:
            return True
    return False


# ---------------------------------------------------------------------------
# Master reconciliation
# ---------------------------------------------------------------------------
def recompute_unit_posture(unit):
    """Recompute all derived posture fields and bump the unit if anything changed."""
    if unit["operating_status"] == "DECOMMISSIONED":
        # terminal: only ensure monitoring stays off
        before = (unit["monitoring_health"],)
        unit["monitoring_health"] = "OFFLINE"
        if (unit["monitoring_health"],) != before:
            db.touch(unit)
        return

    snapshot = _snapshot(unit)

    # 1) compliance + last_exercise
    recompute_compliance(unit)

    # 2) recall posture dominates
    overdue_mandatory = unit_has_overdue_mandatory(unit["id"])

    if overdue_mandatory:
        unit["operating_status"] = "NON_COMPLIANT"
        unit["warranty_status"] = "VOID"
        unit["monitoring_health"] = "OFFLINE"
    else:
        # leaving / not in NON_COMPLIANT: recompute warranty_status
        unit["warranty_status"] = "ACTIVE" if within_warranty_window(unit) else "LAPSED"
        # maintenance posture
        if has_due_active_plan(unit["id"]):
            unit["operating_status"] = "SERVICE_DUE"
        else:
            unit["operating_status"] = "OPERATIONAL"
        # monitoring health (parallel axis)
        recompute_monitoring(unit)

    if _snapshot(unit) != snapshot:
        db.touch(unit)


def _snapshot(unit):
    return (
        unit["operating_status"],
        unit["monitoring_health"],
        unit["warranty_status"],
        unit["compliance_score"],
        unit["last_exercise_at"],
        unit["runtime_hours"],
    )


# ---------------------------------------------------------------------------
# Clock-advance sweeps (PRD §2.4)
# ---------------------------------------------------------------------------
def sweep_all():
    """Run on clock advance: visit-miss + remediation-overdue, then recompute posture."""
    now = get_now()
    touched_units = set()

    # Visits: SCHEDULED past grace -> MISSED
    for visit in db.maintenance_visits.values():
        if visit["status"] != "SCHEDULED":
            continue
        sched = parse(visit["scheduled_for"])
        if sched is None:
            continue
        if sched + timedelta(days=calc.GRACE_DAYS) < now:
            visit["status"] = "MISSED"
            db.touch(visit)
            touched_units.add(visit["unit_id"])

    # Remediations: PENDING/SCHEDULED past deadline -> OVERDUE
    for rem in db.recall_remediations.values():
        if rem["status"] not in ("PENDING", "SCHEDULED"):
            continue
        deadline = parse(rem["deadline_at"])
        if deadline is not None and deadline < now:
            rem["status"] = "OVERDUE"
            db.touch(rem)
            touched_units.add(rem["unit_id"])

    # Recompute posture for every unit (compliance + due plans depend on clock).
    for unit in db.units.values():
        recompute_unit_posture(unit)
