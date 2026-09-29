"""Employees, training modules and training assignments (PRD 3.1 / 3.4)."""

from flask import Blueprint

import constants as C
import sync
from db import fmt_dt, new_row, plus_days, store
from errors import ApiError
from middleware import authenticate
from routes.common import filtered, lookup, paged, single
from validation import (bool_field, body, dt_field, enum_field,
                        enum_list_field, id_field, int_field,
                        nullable_enum_field, qs_bool, qs_enum, qs_str,
                        str_field)

bp = Blueprint("people", __name__)

READ_EMPLOYEE_ROLES = ("ProgramAdmin", "HRPartner", "SafetyOfficer", "SiteManager",
                       "SecurityCoordinator", "ThreatTeamLead", "ComplianceAuditor")
READ_MODULE_ROLES = ("ProgramAdmin", "HRPartner", "SafetyOfficer", "Employee", "ComplianceAuditor")
READ_ASSIGNMENT_ROLES = ("ProgramAdmin", "HRPartner", "SafetyOfficer", "Employee",
                         "SecurityCoordinator", "ComplianceAuditor")

BALLOT_FIELDS = {
    "ballot_value": None,
    "ballot_round": None,
    "ballot_weight": None,
    "ballot_share": None,
    "ballot_submitted_at": None,
    "rationale": None,
}


# ---------------------------------------------------------------- employees


@bp.post("/employees")
def create_employee():
    authenticate(("ProgramAdmin",))
    data = body()
    worksite_id = id_field(data, "worksite_id", True)
    work_area_id = id_field(data, "work_area_id", False)
    full_name = str_field(data, "full_name", True, 1, 120)
    job_function = enum_field(data, "job_function", C.JOB_FUNCTIONS, True)
    team_discipline = nullable_enum_field(data, "team_discipline", C.TEAM_DISCIPLINES)

    lookup(store.worksites, worksite_id, "ERR_WORKSITE_NOT_FOUND")
    if work_area_id is not None:
        lookup(store.work_areas, work_area_id, "ERR_WORK_AREA_NOT_FOUND")

    row = new_row({
        "worksite_id": worksite_id,
        "work_area_id": work_area_id,
        "full_name": full_name,
        "job_function": job_function,
        "team_discipline": team_discipline,
        "employment_status": "ACTIVE",
        "separated_at": None,
        "escort_committed_minutes": 0,
        "active_restriction_count": 0,
        "training_current": False,
    })
    store.employees[row["id"]] = row

    # A new employee introduces new training obligations.
    sync.sync_plans_of_worksite(worksite_id)
    return single(row, 201)


@bp.get("/employees/<employee_id>")
def get_employee(employee_id):
    authenticate(READ_EMPLOYEE_ROLES)
    return single(lookup(store.employees, employee_id, "ERR_EMPLOYEE_NOT_FOUND"))


@bp.get("/employees")
def list_employees():
    authenticate(READ_EMPLOYEE_ROLES)
    filters = {
        "worksite_id": qs_str("worksite_id"),
        "work_area_id": qs_str("work_area_id"),
        "job_function": qs_enum("job_function", C.JOB_FUNCTIONS),
        "team_discipline": qs_enum("team_discipline", C.TEAM_DISCIPLINES),
        "employment_status": qs_enum("employment_status", C.EMPLOYMENT_STATUSES),
        "training_current": qs_bool("training_current"),
    }
    return paged(filtered(list(store.employees.values()), filters))


@bp.post("/employees/<employee_id>/separate")
def separate_employee(employee_id):
    authenticate(("HRPartner",))
    data = body()
    str_field(data, "separation_reason", True, 1)

    employee = lookup(store.employees, employee_id, "ERR_EMPLOYEE_NOT_FOUND")
    if employee["employment_status"] != "ACTIVE":
        raise ApiError("ERR_EMPLOYEE_INVALID_STATE", "The employee is already SEPARATED.")

    sync.assign(employee, {
        "employment_status": "SEPARATED",
        "separated_at": store.clock_raw,
    })

    # 1 -- every escort commitment they hold is revoked.
    touched_cases = []
    for action in list(store.case_actions.values()):
        if action["action_type"] != "SECURITY_ESCORT":
            continue
        if action.get("escort_employee_id") != employee["id"]:
            continue
        if action["status"] not in C.COVERED_STATUSES:
            continue
        sync.release_protective(action, "REVOKED")
        case = store.threat_cases.get(action["case_id"])
        if case is not None and case not in touched_cases:
            touched_cases.append(case)

    # 2 and 3 -- coverage is recomputed and a flip to GAP generates follow-up work.
    for case in touched_cases:
        sync.sync_case_coverage(case)

    # 5 -- every ASSIGNED team seat becomes RECUSED with its ballot fields cleared.
    recused_cases = []
    for seat in list(store.team_assignments.values()):
        if seat.get("member_employee_id") != employee["id"]:
            continue
        if seat["status"] != "ASSIGNED":
            continue
        values = {"status": "RECUSED"}
        values.update(BALLOT_FIELDS)
        sync.assign(seat, values)
        case = store.threat_cases.get(seat["case_id"])
        if case is not None and case not in recused_cases:
            recused_cases.append(case)
    for case in recused_cases:
        sync.sync_case_quorum(case)

    sync.sync_employee_ledger(employee)
    sync.sync_employee_training(employee)
    sync.sync_plans_of_worksite(employee["worksite_id"])
    return single(employee)


# --------------------------------------------------------- training modules


@bp.post("/training-modules")
def create_module():
    authenticate(("ProgramAdmin",))
    data = body()
    code = str_field(data, "code", True, 1, 40)
    scope = enum_list_field(data, "job_function_scope", C.JOB_FUNCTIONS, True, 1)
    scenario_set_version = str_field(data, "scenario_set_version", True, 1)
    refresh_interval_days = int_field(data, "refresh_interval_days", False, 30, 1095, 365)
    passing_score = int_field(data, "passing_score", False, 0, 100, 80)
    required_for_escort = bool_field(data, "required_for_escort", False, False)

    row = new_row({
        "code": code,
        "job_function_scope": scope,
        "scenario_set_version": scenario_set_version,
        "refresh_interval_days": refresh_interval_days,
        "passing_score": passing_score,
        "required_for_escort": required_for_escort,
    })
    store.training_modules[row["id"]] = row

    # Publishing a module widens the training obligation across the organisation.
    sync.sync_all_plans()
    return single(row, 201)


@bp.get("/training-modules/<module_id>")
def get_module(module_id):
    authenticate(READ_MODULE_ROLES)
    return single(lookup(store.training_modules, module_id, "ERR_TRAINING_MODULE_NOT_FOUND"))


@bp.get("/training-modules")
def list_modules():
    authenticate(READ_MODULE_ROLES)
    filters = {"required_for_escort": qs_bool("required_for_escort")}
    return paged(filtered(list(store.training_modules.values()), filters))


# ------------------------------------------------------ training assignments


@bp.post("/training-assignments")
def create_assignment():
    authenticate(("HRPartner",))
    data = body()
    employee_id = id_field(data, "employee_id", True)
    module_id = id_field(data, "module_id", True)
    due_at, _ = dt_field(data, "due_at", True)
    expected_employee_version = int_field(data, "expected_employee_version", True)

    employee = lookup(store.employees, employee_id, "ERR_EMPLOYEE_NOT_FOUND")
    module = lookup(store.training_modules, module_id, "ERR_TRAINING_MODULE_NOT_FOUND")

    # Step 8 -- optimistic concurrency on the employee.
    if expected_employee_version != employee["version"]:
        raise ApiError("ERR_STALE_EMPLOYEE_VERSION", "The employee has moved on since it was read.")

    # Step 19 -- the module must scope the learner's job function.
    if employee["job_function"] not in module["job_function_scope"]:
        raise ApiError("ERR_MODULE_SCOPE_MISMATCH", "The module does not cover this job function.")

    row = new_row({
        "employee_id": employee_id,
        "module_id": module_id,
        "due_at": due_at,
        "status": "ASSIGNED",
        "assigned_at": store.clock_raw,
        "completed_at": None,
        "score": None,
        "expires_at": None,
        "scenario_set_version": None,
        "attempt_count": 0,
    })
    store.training_assignments[row["id"]] = row

    # The annual refresh supersedes the pair's prior assignment.
    for other in list(store.training_assignments.values()):
        if other["id"] == row["id"]:
            continue
        if other["employee_id"] != employee_id or other["module_id"] != module_id:
            continue
        if other["status"] in ("ASSIGNED", "COMPLETED", "EXPIRED"):
            sync.assign(other, {"status": "SUPERSEDED"})

    # The create increments the learner's version by one.
    sync.touch(employee)
    sync.sync_employee_training(employee)
    sync.sync_plans_of_worksite(employee["worksite_id"])
    return single(row, 201)


@bp.get("/training-assignments/<training_assignment_id>")
def get_assignment(training_assignment_id):
    authenticate(READ_ASSIGNMENT_ROLES)
    return single(lookup(store.training_assignments, training_assignment_id,
                         "ERR_TRAINING_ASSIGNMENT_NOT_FOUND"))


@bp.get("/training-assignments")
def list_assignments():
    authenticate(READ_ASSIGNMENT_ROLES)
    filters = {
        "employee_id": qs_str("employee_id"),
        "module_id": qs_str("module_id"),
        "status": qs_enum("status", C.TRAINING_STATUSES),
    }
    return paged(filtered(list(store.training_assignments.values()), filters))


@bp.post("/training-assignments/<training_assignment_id>/complete")
def complete_assignment(training_assignment_id):
    caller = authenticate(("Employee", "HRPartner"))
    data = body()
    score = int_field(data, "score", True, 0, 100)

    assignment = lookup(store.training_assignments, training_assignment_id,
                        "ERR_TRAINING_ASSIGNMENT_NOT_FOUND")

    # Step 7 -- an Employee may only complete their own assignment.
    if caller.role == "Employee" and assignment["employee_id"] != caller.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "This assignment belongs to another employee.")

    # Step 9 -- only an ASSIGNED assignment may be completed.
    if assignment["status"] != "ASSIGNED":
        raise ApiError("ERR_TRAINING_INVALID_STATE", "Only an ASSIGNED assignment may be completed.")

    module = store.training_modules.get(assignment["module_id"])
    employee = store.employees.get(assignment["employee_id"])

    # Step 27 -- a failed attempt still consumes an attempt.
    if module is not None and score < module["passing_score"]:
        sync.assign(assignment, {"attempt_count": assignment["attempt_count"] + 1})
        raise ApiError("ERR_TRAINING_SCORE_BELOW_PASSING",
                       "The score is below the module's passing score.")

    completed_at = store.clock_raw
    expires_at = fmt_dt(plus_days(store.clock, module["refresh_interval_days"]))
    sync.assign(assignment, {
        "status": "COMPLETED",
        "completed_at": completed_at,
        "score": score,
        "expires_at": expires_at,
        "scenario_set_version": module["scenario_set_version"],
        "attempt_count": assignment["attempt_count"] + 1,
    })

    sync.sync_employee_training(employee)
    if employee is not None:
        sync.sync_plans_of_worksite(employee["worksite_id"])
    return single(assignment)
