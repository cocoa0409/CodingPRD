"""Protective measures and post-incident actions (PRD 3.8)."""

from decimal import Decimal

from flask import Blueprint

import calc
import constants as C
import sync
from db import new_row, plus_minutes, store
from errors import ApiError
from middleware import authenticate
from routes.common import filtered, lookup, paged, single
from validation import (body, dt_field, enum_field, id_field, qs_bool,
                        qs_enum, qs_str, str_field)

bp = Blueprint("actions", __name__)

READ_ACTION_ROLES = ("SecurityCoordinator", "HRPartner", "ThreatTeamLead", "SafetyOfficer",
                     "ComplianceAuditor", "ProgramAdmin")

HOLD_STATUSES = ("ALLEGED", "UNDER_REVIEW", "SUBSTANTIATED")
ADVERSE_TYPES = ("SCHEDULE_CHANGE", "ACCESS_RESTRICTION")


def _escort_qualified(employee):
    """Every escort-required module must hold a live COMPLETED assignment."""
    if employee is None or employee["employment_status"] != "ACTIVE":
        return False
    clock = store.clock
    for module in store.training_modules.values():
        if not module.get("required_for_escort"):
            continue
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
            return False
    return True


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open overlap."""
    return a_start < b_end and a_end > b_start


@bp.post("/case-actions")
def create_action():
    authenticate(("SecurityCoordinator", "HRPartner"))
    data = body()
    case_id = id_field(data, "case_id", True)
    action_class = enum_field(data, "action_class", C.ACTION_CLASSES, True)
    action_type = enum_field(data, "action_type", C.ACTION_TYPES, True)
    subject_employee_id = id_field(data, "subject_employee_id", False)
    work_area_id = id_field(data, "work_area_id", False)
    escort_employee_id = id_field(data, "escort_employee_id", False)
    assigned_employee_id = id_field(data, "assigned_employee_id", False)
    starts_at, starts_dt = dt_field(data, "starts_at", False)
    ends_at, ends_dt = dt_field(data, "ends_at", False)
    due_at, _due_dt = dt_field(data, "due_at", False)
    note = str_field(data, "note", False)

    # Step 6 -- body foreign keys in the endpoint's declared input order.
    case = lookup(store.threat_cases, case_id, "ERR_THREAT_CASE_NOT_FOUND")
    if subject_employee_id is not None:
        lookup(store.employees, subject_employee_id, "ERR_EMPLOYEE_NOT_FOUND")
    area = None
    if work_area_id is not None:
        area = lookup(store.work_areas, work_area_id, "ERR_WORK_AREA_NOT_FOUND")
    escort = None
    if escort_employee_id is not None:
        escort = lookup(store.employees, escort_employee_id, "ERR_EMPLOYEE_NOT_FOUND")
    if assigned_employee_id is not None:
        lookup(store.employees, assigned_employee_id, "ERR_EMPLOYEE_NOT_FOUND")

    # Step 11 -- a frozen plan is a hard stop on operational writes.
    plan = store.prevention_plans.get(case.get("plan_id"))
    worksite = store.worksites.get(plan["worksite_id"]) if plan is not None else None
    if plan is None or calc.compliance_posture(plan, worksite) == "FROZEN":
        raise ApiError("ERR_PLAN_POSTURE_FROZEN", "The governing prevention plan is FROZEN.")

    # Step 12 -- interval shape, before any window or overlap arithmetic.
    if action_class == "PROTECTIVE":
        if starts_dt is None or ends_dt is None or starts_dt >= ends_dt:
            raise ApiError("ERR_INVALID_INTERVAL",
                           "A protective measure needs starts_at strictly before ends_at.")
    else:
        if due_at is None or starts_at is not None or ends_at is not None:
            raise ApiError("ERR_INVALID_INTERVAL",
                           "A post-incident action needs due_at and no interval.")

    # Step 13 -- the anti-retaliation hold outranks every rule below it.
    if action_type in ADVERSE_TYPES and subject_employee_id is not None:
        for report in store.incident_reports.values():
            if report["retaliation_status"] not in HOLD_STATUSES:
                continue
            if report.get("retaliation_claimant_employee_id") == subject_employee_id:
                raise ApiError("ERR_ANTI_RETALIATION_HOLD",
                               "An anti-retaliation hold protects this employee.")

    # Step 14 -- escort qualification.
    if action_type == "SECURITY_ESCORT" and escort_employee_id is not None:
        if not _escort_qualified(escort):
            raise ApiError("ERR_ESCORT_NOT_QUALIFIED",
                           "The named escort is not a qualified ACTIVE employee.")

    # Step 17 -- the type must belong to its declared class.
    allowed = C.PROTECTIVE_TYPES if action_class == "PROTECTIVE" else C.POST_INCIDENT_TYPES
    if action_type not in allowed:
        raise ApiError("ERR_ACTION_TYPE_CLASS_MISMATCH",
                       "%s is not a %s action type." % (action_type, action_class))

    # Step 18 -- the field set the specific type requires.
    if action_type == "ACCESS_RESTRICTION":
        if work_area_id is None or subject_employee_id is None:
            raise ApiError("ERR_ACTION_FIELD_MISSING",
                           "An access restriction needs work_area_id and subject_employee_id.")
    elif action_type == "SECURITY_ESCORT":
        if escort_employee_id is None or subject_employee_id is None:
            raise ApiError("ERR_ACTION_FIELD_MISSING",
                           "A security escort needs escort_employee_id and subject_employee_id.")
    elif action_class == "POST_INCIDENT":
        if assigned_employee_id is None:
            raise ApiError("ERR_ACTION_FIELD_MISSING",
                           "A post-incident action needs assigned_employee_id.")

    # Step 19 -- cross-aggregate referential integrity.
    report = store.incident_reports.get(case["incident_report_id"])
    if area is not None and report is not None and area["worksite_id"] != report["worksite_id"]:
        raise ApiError("ERR_WORK_AREA_WORKSITE_MISMATCH",
                       "The work area belongs to another worksite.")

    if action_class == "PROTECTIVE":
        window_start = calc.dt_of(case, "protection_window_start")
        window_end = calc.dt_of(case, "protection_window_end")

        # Step 29 -- the measure must overlap the case's protection window.
        if (
            window_start is None
            or window_end is None
            or not (starts_dt < window_end and ends_dt > window_start)
        ):
            raise ApiError("ERR_MEASURE_OUTSIDE_PROTECTION_WINDOW",
                           "The interval lies outside the case's protection window.")

        # Step 30 -- escort double-booking, with a symmetric 30-minute buffer.
        if action_type == "SECURITY_ESCORT":
            buffered_start = plus_minutes(starts_dt, -C.ESCORT_BUFFER_MINUTES)
            buffered_end = plus_minutes(ends_dt, C.ESCORT_BUFFER_MINUTES)
            for other in store.case_actions.values():
                if other["action_type"] != "SECURITY_ESCORT":
                    continue
                if other["status"] not in C.COVERED_STATUSES:
                    continue
                if other.get("escort_employee_id") != escort_employee_id:
                    continue
                other_start = calc.dt_of(other, "starts_at")
                other_end = calc.dt_of(other, "ends_at")
                if other_start is None or other_end is None:
                    continue
                if _overlaps(buffered_start, buffered_end, other_start, other_end):
                    raise ApiError("ERR_ESCORT_DOUBLE_BOOKED",
                                   "The escort is already committed over this interval.")

        # Step 31 -- the area restriction ceiling, plain half-open overlap.
        if action_type == "ACCESS_RESTRICTION":
            ceiling = max(1, int(Decimal(area["occupancy_cap"]) * C.AREA_RESTRICTION_RATIO))
            concurrent = 0
            for other in store.case_actions.values():
                if other["action_type"] != "ACCESS_RESTRICTION":
                    continue
                if other["status"] not in C.COVERED_STATUSES:
                    continue
                if other.get("work_area_id") != work_area_id:
                    continue
                other_start = calc.dt_of(other, "starts_at")
                other_end = calc.dt_of(other, "ends_at")
                if other_start is None or other_end is None:
                    continue
                if _overlaps(starts_dt, ends_dt, other_start, other_end):
                    concurrent += 1
            if concurrent >= ceiling:
                raise ApiError("ERR_AREA_RESTRICTION_CAPACITY",
                               "The work area already carries its maximum concurrent restrictions.")

    protective = action_class == "PROTECTIVE"
    duration = 0
    if protective:
        duration = int((ends_dt - starts_dt).total_seconds() // 60)

    row = new_row({
        "case_id": case["id"],
        "action_class": action_class,
        "action_type": action_type,
        "subject_employee_id": subject_employee_id,
        "work_area_id": work_area_id if action_type == "ACCESS_RESTRICTION" else None,
        "escort_employee_id": escort_employee_id if action_type == "SECURITY_ESCORT" else None,
        "assigned_employee_id": None if protective else assigned_employee_id,
        "starts_at": starts_at if protective else None,
        "ends_at": ends_at if protective else None,
        "due_at": None if protective else due_at,
        "note": note,
        "status": "SCHEDULED" if protective else "PENDING",
        "duration_minutes": duration,
        "completed_at": None,
        "late_flag": False,
        "revoked_at": None,
        "revocation_reason": None,
        "auto_generated": False,
    })
    store.case_actions[row["id"]] = row

    # The conserved ledgers move the moment the commitment exists.
    if action_type == "SECURITY_ESCORT":
        sync.sync_employee_ledger(store.employees.get(escort_employee_id))
    if action_type == "ACCESS_RESTRICTION":
        sync.sync_employee_ledger(store.employees.get(subject_employee_id))
        sync.sync_area(area)

    sync.sync_case_actions_count(case)
    sync.sync_case_coverage(case, allow_auto_action=False)
    if plan["status"] != "SUPERSEDED":
        sync.sync_plan(plan)
    return single(row, 201)


@bp.get("/case-actions/<case_action_id>")
def get_action(case_action_id):
    authenticate(READ_ACTION_ROLES)
    return single(lookup(store.case_actions, case_action_id, "ERR_CASE_ACTION_NOT_FOUND"))


@bp.get("/case-actions")
def list_actions():
    authenticate(READ_ACTION_ROLES)
    filters = {
        "case_id": qs_str("case_id"),
        "subject_employee_id": qs_str("subject_employee_id"),
        "work_area_id": qs_str("work_area_id"),
        "escort_employee_id": qs_str("escort_employee_id"),
        "assigned_employee_id": qs_str("assigned_employee_id"),
        "action_class": qs_enum("action_class", C.ACTION_CLASSES),
        "action_type": qs_enum("action_type", C.ACTION_TYPES),
        "status": qs_enum("status", C.ACTION_STATUSES),
        "auto_generated": qs_bool("auto_generated"),
    }
    return paged(filtered(list(store.case_actions.values()), filters))


@bp.post("/case-actions/<case_action_id>/revoke")
def revoke_action(case_action_id):
    authenticate(("SecurityCoordinator",))
    data = body()
    revocation_reason = str_field(data, "revocation_reason", True, 1)

    action = lookup(store.case_actions, case_action_id, "ERR_CASE_ACTION_NOT_FOUND")

    if action["action_class"] != "PROTECTIVE" or action["status"] not in C.COVERED_STATUSES:
        raise ApiError("ERR_ACTION_INVALID_STATE",
                       "Only a SCHEDULED or ACTIVE protective measure may be revoked.")

    sync.release_protective(action, "REVOKED", revocation_reason)

    case = store.threat_cases.get(action["case_id"])
    sync.sync_case_coverage(case)
    sync.sync_case_actions_count(case)
    if case is not None:
        plan = store.prevention_plans.get(case.get("plan_id"))
        if plan is not None and plan["status"] != "SUPERSEDED":
            sync.sync_plan(plan)
    return single(action)


@bp.post("/case-actions/<case_action_id>/complete")
def complete_action(case_action_id):
    authenticate(("HRPartner", "SecurityCoordinator"))
    data = body()
    str_field(data, "completion_note", False)

    action = lookup(store.case_actions, case_action_id, "ERR_CASE_ACTION_NOT_FOUND")

    if action["action_class"] != "POST_INCIDENT" or action["status"] not in ("PENDING", "OVERDUE"):
        raise ApiError("ERR_ACTION_INVALID_STATE",
                       "Only a PENDING or OVERDUE post-incident action may be completed.")

    completed_at = store.clock_raw
    due = calc.dt_of(action, "due_at")
    late = bool(due is not None and store.clock > due)
    sync.assign(action, {
        "status": "COMPLETED",
        "completed_at": completed_at,
        "late_flag": late,
    })

    case = store.threat_cases.get(action["case_id"])
    sync.sync_case_actions_count(case)
    if case is not None:
        plan = store.prevention_plans.get(case.get("plan_id"))
        if plan is not None and plan["status"] != "SUPERSEDED":
            sync.sync_plan(plan)
    return single(action)
