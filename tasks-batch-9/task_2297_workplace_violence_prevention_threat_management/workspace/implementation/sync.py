"""Derived-field reconciliation and cascading side effects.

PRD 2.4: recomputation counts as mutation -- a refreshed row's updated_at moves
and its version increments.  A row's version moves at most once per request, so
a create that is documented as "increments the plan's version by one" does
exactly that even when it also refreshes that plan's aggregates.
"""


from flask import g

import calc
import constants as C
from db import (fmt_dt, new_log_row, new_row, parse_dt, plus_days,
                plus_minutes, plus_years, real_now_iso, store)


def _dirty():
    marks = getattr(g, "_dirty_rows", None)
    if marks is None:
        marks = set()
        g._dirty_rows = marks
    return marks


def touch(row):
    """Bump version/updated_at at most once per request for this row."""
    if "version" not in row:
        return
    marks = _dirty()
    if row["id"] in marks:
        return
    marks.add(row["id"])
    row["version"] += 1
    row["updated_at"] = real_now_iso()


def freeze(row):
    """Mark a freshly created row so its initial derived-field pass leaves version at 1."""
    _dirty().add(row["id"])


def assign(row, values):
    """Apply changed fields and bump the row when anything actually moved."""
    changed = False
    for key, value in values.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


# --------------------------------------------------------------- worksites


def sync_worksite_risk(worksite):
    """violent_incident_count_12mo and high_risk_flag."""
    if worksite is None:
        return False
    clock = store.clock
    horizon = plus_days(clock, -365)
    count = 0
    for entry in calc.entries_of_worksite(worksite["id"]):
        if entry["retention_status"] != "ACTIVE":
            continue
        if calc.is_superseded_entry(entry):
            continue
        incident_at = calc.dt_of(entry, "incident_at")
        if incident_at is None:
            continue
        if horizon <= incident_at <= clock:
            count += 1
    return assign(worksite, {
        "violent_incident_count_12mo": count,
        "high_risk_flag": count >= 1,
    })


# -------------------------------------------------------------- work areas


def sync_area(area):
    if area is None:
        return
    restricted = len([
        a for a in store.case_actions.values()
        if a["action_type"] == "ACCESS_RESTRICTION"
        and a["status"] in C.COVERED_STATUSES
        and a.get("work_area_id") == area["id"]
    ])
    score = None
    plan = calc.governing_plan(area["worksite_id"])
    if plan is not None:
        for assessment in calc.assessments_of_plan(plan["id"]):
            if assessment["work_area_id"] == area["id"] and assessment["status"] != "SUPERSEDED":
                score = assessment["hazard_score"]
                break
    assign(area, {"restricted_employee_count": restricted, "current_hazard_score": score})


def sync_areas_of_worksite(worksite_id):
    for area in calc.areas_of_worksite(worksite_id):
        sync_area(area)


# ---------------------------------------------------------------- employees


def sync_employee_ledger(employee):
    if employee is None:
        return
    minutes = 0
    restrictions = 0
    for action in store.case_actions.values():
        if action["status"] not in C.COVERED_STATUSES:
            continue
        if action["action_type"] == "SECURITY_ESCORT" and action.get("escort_employee_id") == employee["id"]:
            minutes += action.get("duration_minutes") or 0
        if action["action_type"] == "ACCESS_RESTRICTION" and action.get("subject_employee_id") == employee["id"]:
            restrictions += 1
    assign(employee, {
        "escort_committed_minutes": minutes,
        "active_restriction_count": restrictions,
    })


def sync_employee_training(employee):
    """training_current: every module scoping this job function has a live pass."""
    if employee is None:
        return
    clock = store.clock
    applicable = [
        m for m in store.training_modules.values()
        if employee["job_function"] in m["job_function_scope"]
    ]
    current = True
    for module in applicable:
        satisfied = False
        for assignment in store.training_assignments.values():
            if assignment["employee_id"] != employee["id"]:
                continue
            if assignment["module_id"] != module["id"]:
                continue
            if assignment["status"] != "COMPLETED":
                continue
            expires = calc.dt_of(assignment, "expires_at")
            if expires is not None and expires > clock:
                satisfied = True
                break
        if not satisfied:
            current = False
            break
    assign(employee, {"training_current": current})


# --------------------------------------------------------------------- plans


def sync_plan(plan):
    if plan is None:
        return
    worksite = store.worksites.get(plan["worksite_id"])
    metrics = calc.plan_compliance_metrics(plan)
    posture = calc.compliance_posture(plan, worksite)
    readiness = calc.inspection_readiness(plan, metrics, posture)
    values = dict(metrics)
    values["compliance_posture"] = posture
    values.update(readiness)
    assign(plan, values)


def sync_plans_of_worksite(worksite_id):
    for plan in calc.plans_of_worksite(worksite_id):
        if plan["status"] == "SUPERSEDED":
            continue
        sync_plan(plan)


def sync_all_plans():
    """Every non-SUPERSEDED plan in the system."""
    plans = [p for p in store.prevention_plans.values() if p["status"] != "SUPERSEDED"]
    for plan in plans:
        sync_plan(plan)
    return len(plans)


# --------------------------------------------------------------------- cases


def sync_case_quorum(case):
    if case is None:
        return
    report = store.incident_reports.get(case["incident_report_id"])
    quorum = calc.team_quorum(case, report)
    assign(case, {
        "quorum_met": quorum["quorum_met"],
        "ballot_count_current_round": calc.ballot_count_current_round(case),
    })


def sync_case_actions_count(case):
    if case is None:
        return
    open_count = len([
        a for a in calc.actions_of_case(case["id"])
        if a["action_class"] == "POST_INCIDENT" and a["status"] in ("PENDING", "OVERDUE")
    ])
    assign(case, {"open_action_count": open_count})


def sync_case_coverage(case, allow_auto_action=True):
    """Recompute the coverage gap; a flip to GAP while MONITORING generates work."""
    if case is None:
        return
    previous = case.get("protection_status")
    gap_hours, status = calc.coverage_gap(case)
    assign(case, {
        "coverage_gap_hours": calc.num(gap_hours),
        "protection_status": status,
    })
    if (
        allow_auto_action
        and status == "GAP"
        and previous == "COVERED"
        and case["status"] == "MONITORING"
    ):
        create_auto_safety_plan_review(case)


def sync_case(case, allow_auto_action=True):
    sync_case_quorum(case)
    sync_case_actions_count(case)
    sync_case_coverage(case, allow_auto_action=allow_auto_action)


def create_auto_safety_plan_review(case):
    """PRD 3.8: an automatic SAFETY_PLAN_REVIEW due 24h after the logical clock."""
    action = new_row({
        "case_id": case["id"],
        "action_class": "POST_INCIDENT",
        "action_type": "SAFETY_PLAN_REVIEW",
        "subject_employee_id": case.get("protected_employee_id"),
        "work_area_id": None,
        "escort_employee_id": None,
        "assigned_employee_id": case.get("lead_employee_id"),
        "starts_at": None,
        "ends_at": None,
        "due_at": fmt_dt(plus_minutes(store.clock, C.AUTO_SAFETY_REVIEW_HOURS * 60)),
        "note": None,
        "status": "PENDING",
        "duration_minutes": 0,
        "completed_at": None,
        "late_flag": False,
        "revoked_at": None,
        "revocation_reason": None,
        "auto_generated": True,
    })
    store.case_actions[action["id"]] = action
    sync_case_actions_count(case)
    plan = store.prevention_plans.get(case.get("plan_id"))
    if plan is not None and plan["status"] != "SUPERSEDED":
        sync_plan(plan)
    return action


# ------------------------------------------------- violent incident log entries


# PRD 3.9: the eight regulatory elements, in the documented order.
REQUIRED_LOG_ELEMENTS = (
    "incident_at",
    "work_area_name",
    "incident_type",
    "perpetrator_class",
    "injury_level",
    "law_enforcement_notified",
    "consequence_narrative",
    "controls_summary",
)


def perpetrator_class_of(report):
    typology = report["incident_type"]
    if typology == "TYPE_1_CRIMINAL":
        return "STRANGER"
    if typology == "TYPE_2_CLIENT":
        return "CLIENT"
    if typology == "TYPE_4_DOMESTIC":
        return "DOMESTIC_PARTNER"
    return "COWORKER" if report.get("subject_employee_id") else "UNKNOWN"


def law_enforcement_notified_for(case_id):
    """True when a law-enforcement-coordination action exists in a live status."""
    for action in store.case_actions.values():
        if action["case_id"] != case_id:
            continue
        if action["action_type"] != "LAW_ENFORCEMENT_COORDINATION":
            continue
        if action["status"] in ("PENDING", "OVERDUE", "COMPLETED"):
            return True
    return False


def count_required_elements(fields):
    return len([name for name in REQUIRED_LOG_ELEMENTS if fields.get(name) is not None])


def append_log_entry(case, report):
    """The automatic entry written by a substantiating decision: six of eight."""
    area = store.work_areas.get(report.get("work_area_id"))
    incident_at = report.get("occurred_at")
    retention = None
    if incident_at is not None:
        try:
            retention = fmt_dt(plus_years(parse_dt(incident_at), C.LOG_RETENTION_YEARS))
        except Exception:
            retention = None

    fields = {
        "worksite_id": report["worksite_id"],
        "incident_report_id": report["id"],
        "case_id": case["id"],
        "supersedes_entry_id": None,
        "incident_at": incident_at,
        "work_area_name": area["name"] if area is not None else None,
        "incident_type": report["incident_type"],
        "perpetrator_class": perpetrator_class_of(report),
        "injury_level": report["injury_level"],
        "weapon_involved": report["weapon_involved"],
        "law_enforcement_notified": law_enforcement_notified_for(case["id"]),
        "consequence_narrative": None,
        "controls_summary": None,
        "required_element_count_present": 0,
        "amendment_reason": None,
        "retention_expiry_date": retention,
        "retention_status": "ACTIVE",
    }
    fields["required_element_count_present"] = count_required_elements(fields)
    row = new_log_row(fields)
    store.log_entries[row["id"]] = row
    return row


def release_protective(action, new_status, reason=None):
    """Move a protective measure out of the conserved set and release its credits."""
    values = {"status": new_status}
    if new_status == "REVOKED":
        values["revoked_at"] = store.clock_raw
        if reason is not None:
            values["revocation_reason"] = reason
    assign(action, values)

    if action["action_type"] == "SECURITY_ESCORT" and action.get("escort_employee_id"):
        sync_employee_ledger(store.employees.get(action["escort_employee_id"]))
    if action["action_type"] == "ACCESS_RESTRICTION":
        if action.get("subject_employee_id"):
            sync_employee_ledger(store.employees.get(action["subject_employee_id"]))
        if action.get("work_area_id"):
            sync_area(store.work_areas.get(action["work_area_id"]))
