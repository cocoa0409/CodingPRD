"""Employees, leaves of absence, role changes, and manual assignment issuance."""
from datetime import timedelta

from flask import Blueprint, request

from db import new_entity, now, store, touch
from errors import ApiError, bad_request, not_found
from middleware import require_any_authenticated, require_roles
from response import (get_body, list_response, pub, req_dt, req_str, success)
from services import (apply_role_change, create_assignment, reverse_role_change,
                      terminate_employee, NON_TERMINAL)

bp = Blueprint("people", __name__)

EMPLOYEE_STATUSES = ("ACTIVE", "ON_LEAVE", "TERMINATED")
ROLE_CHANGE_STATUSES = ("SCHEDULED", "APPLIED", "CANCELLED", "REVERSED")


def get_employee(eid):
    e = store.employees.get(eid)
    if e is None:
        raise not_found("employee not found")
    return e


def get_role_change(rid):
    rc = store.role_changes.get(rid)
    if rc is None:
        raise not_found("role change not found")
    return rc


def normalize_leave_dates(start_raw, end_raw):
    """start_date -> first day 00:00:00Z; end_date -> last day 23:59:59Z (closed interval)."""
    s = start_raw.replace(hour=0, minute=0, second=0, microsecond=0)
    e = end_raw.replace(hour=23, minute=59, second=59, microsecond=0)
    return s, e


# ------------------------------------------------------------------ employees

@bp.post("/employees")
def create_employee():
    require_roles("HRAdmin")
    body = get_body()
    employee_no = req_str(body, "employee_no")
    full_name = req_str(body, "full_name")
    hired_at = req_dt(body, "hired_at")
    current_role_id = req_str(body, "current_role_id")
    manager_id = None
    if "manager_id" in body and body["manager_id"] is not None:
        manager_id = body["manager_id"]
        if not isinstance(manager_id, str):
            raise bad_request("manager_id must be a string")
    role = store.roles.get(current_role_id)
    if role is None:
        raise not_found("role not found")
    if manager_id is not None and manager_id not in store.employees:
        raise not_found("manager not found")
    for e in store.employees.values():
        if e["employee_no"] == employee_no:
            raise bad_request("employee_no must be unique")
    emp = new_entity()
    emp.update({
        "employee_no": employee_no, "full_name": full_name, "hired_at": hired_at,
        "manager_id": manager_id, "current_role_id": current_role_id,
        "status": "ACTIVE", "compliance_blocked": False, "verified_completed_count": 0,
    })
    store.employees[emp["id"]] = emp
    # NEW_HIRE sweep: one assignment per ACTIVE requirement of the employee's role.
    reqs = [r for r in store.requirements.values()
            if r["role_id"] == current_role_id and r["status"] == "ACTIVE"]
    reqs.sort(key=lambda r: r["created_at"])
    for r in reqs:
        if not any(a["employee_id"] == emp["id"] and a["curriculum_id"] == r["curriculum_id"]
                   and a["progress_status"] in ("ASSIGNED", "IN_PROGRESS", "SUBMITTED", "VERIFIED_COMPLETED")
                   for a in store.assignments.values()):
            create_assignment(emp, r, "NEW_HIRE")
    return success(pub(emp), "object", 201)


@bp.get("/employees")
def list_employees():
    require_any_authenticated()
    mgr = request.args.get("manager_id")
    status = request.args.get("status")
    items = list(store.employees.values())
    if mgr is not None:
        items = [e for e in items if e["manager_id"] == mgr]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items.sort(key=lambda e: e["created_at"])
    return list_response(items)


@bp.get("/employees/<eid>")
def read_employee(eid):
    require_any_authenticated()
    return success(pub(get_employee(eid)))


@bp.post("/employees/<eid>/terminate")
def terminate(eid):
    require_roles("HRAdmin")
    emp = get_employee(eid)
    if emp["status"] == "TERMINATED":
        raise ApiError("ERR_INVALID_STATE", "employee is already TERMINATED")
    terminate_employee(emp)
    return success(pub(emp))


# --------------------------------------------------------------------- leaves

@bp.post("/employees/<eid>/leaves")
def create_leave(eid):
    require_roles("HRAdmin")
    body = get_body()
    start_raw = req_dt(body, "start_date")
    end_raw = req_dt(body, "end_date")
    reason = req_str(body, "reason")
    start, end = normalize_leave_dates(start_raw, end_raw)
    if end < start:
        raise bad_request("end_date must not be earlier than start_date")
    emp = get_employee(eid)
    if emp["status"] == "TERMINATED":
        raise ApiError("ERR_EMPLOYEE_TERMINATED", "cannot record leave for a TERMINATED employee")
    # Closed intervals + mandatory one-day buffer (PRD 3.3).
    for lv in store.leaves.values():
        if lv["employee_id"] != eid:
            continue
        if start <= lv["end_date"] + timedelta(days=1) and lv["start_date"] <= end + timedelta(days=1):
            raise ApiError("ERR_LEAVE_OVERLAP", "leave window conflicts with an existing leave")
    lv = new_entity()
    lv.update({"employee_id": eid, "start_date": start, "end_date": end, "reason": reason})
    store.leaves[lv["id"]] = lv
    # A leave covering the current instant flips the employee to ON_LEAVE and freezes.
    t = now()
    if start <= t <= end and emp["status"] == "ACTIVE":
        emp["status"] = "ON_LEAVE"
        touch(emp)
        for a in store.assignments.values():
            if (a["employee_id"] == eid and a["progress_status"] in NON_TERMINAL
                    and a["deadline_status"] != "FROZEN"):
                a["deadline_status"] = "FROZEN"
                touch(a)
    return success(pub(lv), "object", 201)


@bp.get("/employees/<eid>/leaves")
def list_leaves(eid):
    require_any_authenticated()
    get_employee(eid)
    items = [lv for lv in store.leaves.values() if lv["employee_id"] == eid]
    items.sort(key=lambda lv: lv["created_at"])
    return list_response(items)


# --------------------------------------------------------------- role changes

@bp.post("/employees/<eid>/role-changes")
def create_role_change(eid):
    require_roles("HRAdmin")
    body = get_body()
    to_role_id = req_str(body, "to_role_id")
    effective_at = req_dt(body, "effective_at")
    emp = get_employee(eid)
    to_role = store.roles.get(to_role_id)
    if to_role is None:
        raise not_found("role not found")
    # P7 state: terminated employees may not change roles.
    if emp["status"] == "TERMINATED":
        raise ApiError("ERR_EMPLOYEE_TERMINATED", "employee is TERMINATED")
    # P8 temporal beats P9 uniqueness: retroactivity beyond 30 days is rejected first.
    t = now()
    if effective_at < t - timedelta(days=30):
        raise ApiError("ERR_RETROACTIVE_LIMIT_EXCEEDED",
                       "effective_at is more than 30 days in the past")
    # P9: target differs from current; at most one SCHEDULED change per employee.
    if to_role_id == emp["current_role_id"]:
        raise ApiError("ERR_ROLE_UNCHANGED", "to_role_id equals the current role")
    for rc in store.role_changes.values():
        if rc["employee_id"] == eid and rc["status"] == "SCHEDULED":
            raise ApiError("ERR_PENDING_ROLE_CHANGE_EXISTS",
                           "employee already has a SCHEDULED role change")
    # P11: target role must be ACTIVE.
    if to_role["status"] != "ACTIVE":
        raise ApiError("ERR_ROLE_NOT_ACTIVE", "target role is RETIRED")
    from_role = store.roles.get(emp["current_role_id"])
    rc = new_entity()
    rc.update({
        "employee_id": eid,
        "from_role_code": from_role["code"] if from_role else None,
        "to_role_id": to_role_id,
        "effective_at": effective_at,
        "status": "SCHEDULED",
        "applied_at": None,
        "reversed_at": None,
    })
    store.role_changes[rc["id"]] = rc
    if effective_at <= t:
        apply_role_change(rc)  # synchronous application (stamps APPLIED + cascades)
    return success(pub(rc), "object", 201)


@bp.get("/role-changes")
def list_role_changes():
    require_any_authenticated()
    emp_f = request.args.get("employee_id")
    role_f = request.args.get("to_role_id")
    status_f = request.args.get("status")
    items = list(store.role_changes.values())
    if emp_f is not None:
        items = [rc for rc in items if rc["employee_id"] == emp_f]
    if role_f is not None:
        items = [rc for rc in items if rc["to_role_id"] == role_f]
    if status_f is not None:
        items = [rc for rc in items if rc["status"] == status_f]
    items.sort(key=lambda rc: rc["created_at"])
    return list_response(items)


@bp.get("/role-changes/<rid>")
def read_role_change(rid):
    require_any_authenticated()
    return success(pub(get_role_change(rid)))


@bp.post("/role-changes/<rid>/cancel")
def cancel_role_change(rid):
    require_roles("HRAdmin")
    rc = get_role_change(rid)
    if rc["status"] != "SCHEDULED":
        raise ApiError("ERR_ROLE_CHANGE_NOT_CANCELLABLE", "only a SCHEDULED change can be cancelled")
    rc["status"] = "CANCELLED"
    touch(rc)
    return success(pub(rc))


@bp.post("/role-changes/<rid>/reverse")
def reverse(rid):
    require_roles("HRAdmin")
    rc = get_role_change(rid)
    # P7 state gates: must be APPLIED; no ACCEPTED completion on change-created assignments.
    if rc["status"] != "APPLIED":
        raise ApiError("ERR_ROLE_CHANGE_NOT_REVERSIBLE", "only an APPLIED change can be reversed")
    for c in store.completions.values():
        a = store.assignments.get(c["assignment_id"])
        if (a is not None and a["source_role_change_id"] == rc["id"]
                and c["review_status"] == "ACCEPTED"):
            raise ApiError("ERR_ROLE_CHANGE_NOT_REVERSIBLE",
                           "an accepted completion exists on a change-created assignment")
    # P8 temporal: no later than fourteen days after applied_at (inclusive).
    t = now()
    if t > rc["applied_at"] + timedelta(days=14):
        raise ApiError("ERR_RETROACTIVE_LIMIT_EXCEEDED",
                       "reverse window (14 days after applied_at) has passed")
    # P11: the role matching the snapshotted from_role_code must exist and be ACTIVE.
    from_role = next((r for r in store.roles.values() if r["code"] == rc["from_role_code"]), None)
    if from_role is None or from_role["status"] != "ACTIVE":
        raise ApiError("ERR_ROLE_NOT_ACTIVE", "original role is not ACTIVE")
    reverse_role_change(rc, from_role)
    return success(pub(rc))


# ----------------------------------------------------------- manual assignment

@bp.post("/employees/<eid>/assignments")
def create_manual_assignment(eid):
    require_roles("ComplianceAdmin")
    body = get_body()
    req_id = req_str(body, "role_requirement_id")
    emp = get_employee(eid)
    req = store.requirements.get(req_id)
    if req is None:
        raise not_found("requirement not found")
    # P7
    if emp["status"] == "TERMINATED":
        raise ApiError("ERR_EMPLOYEE_TERMINATED", "employee is TERMINATED")
    # P9: no non-terminal assignment for the same (employee, requirement).
    for a in store.assignments.values():
        if (a["employee_id"] == eid and a["role_requirement_id"] == req_id
                and a["progress_status"] in NON_TERMINAL):
            raise ApiError("ERR_DUPLICATE_ACTIVE_ASSIGNMENT",
                           "a non-terminal assignment already exists for this requirement")
    # P10: requirement must belong to the employee's current role.
    if req["role_id"] != emp["current_role_id"]:
        raise ApiError("ERR_REQUIREMENT_ROLE_MISMATCH",
                       "requirement's role differs from the employee's current role")
    # P11: requirement and its curriculum must be ACTIVE.
    if req["status"] != "ACTIVE":
        raise ApiError("ERR_REQUIREMENT_NOT_ACTIVE", "requirement is RETIRED")
    curr = store.curricula.get(req["curriculum_id"])
    if curr is None or curr["status"] != "ACTIVE":
        raise ApiError("ERR_CURRICULUM_NOT_ACTIVE", "curriculum is not ACTIVE")
    a = create_assignment(emp, req, "MANUAL")
    return success(pub(a), "object", 201)
