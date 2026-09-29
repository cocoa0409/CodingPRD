"""Shared domain operations: cascades, conditional restoration, re-scoring."""
from __future__ import annotations

import calc
import util
from store import store

NON_TERMINAL_WO = ("INTAKE", "IN_REPAIR", "AWAITING_PARTS", "REPAIR_COMPLETE", "VERIFIED")
OPEN_FINDING_STATES = ("OPEN", "REMEDIATION_SCHEDULED")


# ---------------------------------------------------------------- lookups
def model_of(device):
    return store.get("DeviceModel", device["device_model_id"])


def department_of(device):
    return store.get("Department", device["department_id"])


def facility_of(device):
    return store.get("Facility", device["facility_id"])


def device_of_work_order(work_order):
    return store.get("Device", work_order["device_id"])


def has_open_work_order(device_id, exclude_id=None):
    for wo in store.all("WorkOrder"):
        if wo["device_id"] != device_id:
            continue
        if exclude_id is not None and wo["id"] == exclude_id:
            continue
        if wo["status"] in NON_TERMINAL_WO:
            return True
    return False


def has_open_finding(device_id):
    for finding in store.all("SecurityFinding"):
        if finding["device_id"] == device_id and finding["status"] in OPEN_FINDING_STATES:
            return True
    return False


# ---------------------------------------------------------------- scoring
def recompute_replacement_score(device):
    model = model_of(device)
    if model is None:
        return
    device["replacement_priority_score"] = calc.replacement_priority_score(
        device, model, store.now()
    )


def recompute_classification(device):
    model = model_of(device)
    if model is None:
        return
    score, klass, interval = calc.device_risk_classification(device, model, store.now())
    device["risk_score"] = score
    device["risk_class"] = klass
    device["pm_interval_days"] = interval
    recompute_replacement_score(device)


# ---------------------------------------------------------------- cascades
def conditional_restore(device, exclude_work_order_id=None):
    """PRD 2.10 — DOWN -> IN_SERVICE only when all three guards hold.

    Returns True when the device row was mutated (caller decides on touch()).
    """
    if device["operational_state"] != "DOWN":
        return False
    if has_open_work_order(device["id"], exclude_id=exclude_work_order_id):
        return False
    if device.get("recall_hold"):
        return False
    if device.get("security_state") == "QUARANTINED":
        return False
    device["operational_state"] = "IN_SERVICE"
    return True


def escalate_uncovered(work_order):
    """A cancelled loaner leaves the covered order uncovered (PRD 3.6)."""
    work_order["loaner_status"] = "UNCOVERED"
    if work_order["status"] in ("INTAKE", "IN_REPAIR", "AWAITING_PARTS"):
        work_order["priority"] = "P1"
        work_order["sla_hours"] = 4
    store.touch(work_order)


def cancel_loaner_assignment(assignment, release_pool_unit, escalate=True):
    """DEPLOYED -> CANCELLED with no money conjured."""
    assignment["status"] = "CANCELLED"
    assignment["billable_days"] = 0
    assignment["rental_cost_cents"] = 0
    store.touch(assignment)
    if release_pool_unit and assignment["source"] == "POOL" and assignment.get("loaner_device_id"):
        unit = store.get("Device", assignment["loaner_device_id"])
        if unit is not None and unit["operational_state"] == "ON_LOAN":
            unit["operational_state"] = "IN_SERVICE"
            store.touch(unit)
    if escalate:
        work_order = store.get("WorkOrder", assignment["work_order_id"])
        if work_order is not None:
            escalate_uncovered(work_order)


def cancel_loaners_lending_device(device_id):
    """Every DEPLOYED assignment whose loaner unit is this device is cancelled.

    Used by the quarantine cascade and by the CLASS_I recall cascade; the pool
    unit is NOT released back to IN_SERVICE because it has just been taken DOWN.
    """
    for assignment in store.ordered(
        [a for a in store.all("LoanerAssignment")
         if a.get("loaner_device_id") == device_id and a["status"] == "DEPLOYED"]
    ):
        cancel_loaner_assignment(assignment, release_pool_unit=False)


def quarantine_cascade(device):
    """PRD 3.8 — fires identically from a CRITICAL finding and a direct move."""
    if device["operational_state"] in ("IN_SERVICE", "ON_LOAN"):
        device["operational_state"] = "DOWN"
    cancel_loaners_lending_device(device["id"])


# ---------------------------------------------------------------- fiscal
def apply_budget_state(department):
    """Re-derive budget_state from the post-debit spend and cascade upward."""
    previous = department["budget_state"]
    new_state = calc.budget_state_for(
        department["downtime_spend_cents"], department["downtime_budget_cents"]
    )
    department["budget_state"] = new_state
    if new_state == "ON_HOLD" and previous != "ON_HOLD":
        facility = store.get("Facility", department["facility_id"])
        if facility is not None:
            before = facility["departments_on_hold_count"]
            facility["departments_on_hold_count"] = before + 1
            if before == 0 and facility["ce_posture"] == "NORMAL":
                facility["ce_posture"] = "HEIGHTENED"
            store.touch(facility)


def escalate_posture(facility):
    if facility["ce_posture"] == "NORMAL":
        facility["ce_posture"] = "HEIGHTENED"


# ---------------------------------------------------------------- security
def mitigate_finding(finding, note=None, touch_device=True):
    """Move a finding to MITIGATED and apply its device consequences."""
    finding["status"] = "MITIGATED"
    finding["resolved_at"] = store.now_iso()
    if note is not None:
        finding["resolution_note"] = note
    store.touch(finding)
    device = store.get("Device", finding["device_id"])
    if device is None:
        return
    changed = False
    if device["security_state"] == "QUARANTINED":
        device["security_state"] = "REMEDIATED"
        changed = True
    if conditional_restore(device):
        changed = True
    if changed and touch_device:
        store.touch(device)


# ---------------------------------------------------------------- listing
def paginate(records, limit, offset):
    total = len(records)
    page = records[offset:offset + limit]
    return page, total


def defer_pm_tasks_for_recall(device_id):
    """CLASS_I cascade — SCHEDULED PM tasks with deferral_count < 2 slide 30 days."""
    tasks = store.ordered(
        [t for t in store.all("PMTask")
         if t["device_id"] == device_id and t["status"] == "SCHEDULED" and t["deferral_count"] < 2]
    )
    for task in tasks:
        task["window_start"] = util.format_dt(util.add_days(util.parse_dt(task["window_start"]), 30))
        task["window_end"] = util.format_dt(util.add_days(util.parse_dt(task["window_end"]), 30))
        task["due_at"] = util.format_dt(util.add_days(util.parse_dt(task["due_at"]), 30))
        task["deferral_count"] = task["deferral_count"] + 1
        task["status"] = "DEFERRED"
        store.touch(task)


def new_work_order(device, reported_severity, problem_summary, origin_security_finding_id=None):
    """Create a WorkOrder in INTAKE and take the unit DOWN (PRD 3.4)."""
    priority, sla_hours = calc.work_order_priority(reported_severity, device["risk_class"])
    record = store.new_record("WorkOrder", {
        "device_id": device["id"],
        "vendor_id": None,
        "service_contract_id": None,
        "origin_security_finding_id": origin_security_finding_id,
        "reported_severity": reported_severity,
        "problem_summary": problem_summary,
        "reported_at": store.now_iso(),
        "status": "INTAKE",
        "priority": priority,
        "sla_hours": sla_hours,
        "service_mode": None,
        "assigned_user_id": None,
        "repaired_by_user_id": None,
        "verified_by_user_id": None,
        "repair_started_at": None,
        "repair_completed_at": None,
        "closed_at": None,
        "active_repair_seconds": 0,
        "active_repair_hours": 0.00,
        "turnaround_hours": 0.00,
        "sla_met": False,
        "labor_minutes": 0,
        "parts_cost_cents": 0,
        "shift_multiplier_applied": 1.0,
        "estimated_cost_cents": 0,
        "final_cost_cents": 0,
        "department_charge_cents": 0,
        "verify_fail_count": 0,
        "loaner_status": "NONE",
        "_segment_start": None,
    })
    return record
