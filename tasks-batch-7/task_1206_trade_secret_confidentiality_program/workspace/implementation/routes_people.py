"""Employee, Acknowledgment, ExitInterview, TrainingAssignment routes (PRD §3.3, §3.6)."""

from flask import Blueprint, request

from db import (
    add_days,
    all_rows,
    by_id,
    created_asc,
    db,
    fmt_ts,
    new_record,
    now,
    parse_dt,
    program,
    serialize,
    stamp,
    touch,
)
from errors import (
    err_ack_required,
    err_date_order,
    err_duplicate_email,
    err_grants_remain,
    err_interview_not_certified,
    err_interview_overlap,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
    err_ownership,
    err_policy_stale,
    err_review_not_concluded,
    err_unauthorized_role,
)
from middleware import actor, body, require_enum, require_field, require_roles, require_str
from response import ok_list, ok_object, paginate
from services import ACK_WINDOW_DAYS, recompute_training_current

bp = Blueprint("people", __name__)

CLEARANCES = ("STANDARD", "ELEVATED", "PRIVILEGED")
EMPLOYEE_STATUSES = ("PREBOARDING", "ACTIVE", "NOTICE", "DEPARTED")
DEPARTURE_TYPES = ("VOLUNTARY", "INVOLUNTARY")
ACK_STATUSES = ("PENDING", "SIGNED", "SUPERSEDED", "EXPIRED")
INTERVIEW_STATUSES = ("SCHEDULED", "CONDUCTED", "NO_SHOW", "CERTIFIED", "ESCALATED", "CANCELLED")
TRAINING_MODULES = ("BASIC_TS", "CLEAN_DESK", "ADVANCED_IP")
TRAINING_STATUSES = ("ASSIGNED", "COMPLETED", "OVERDUE", "ESCALATED", "EXCUSED")


def _paginate_list(store_name, filters):
    rows = []
    for r in created_asc(all_rows(store_name)):
        if all(r.get(k) == v for k, v in filters):
            rows.append(serialize(r))
    page, limit, offset, total = paginate(rows, request.args)
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Employee
# ---------------------------------------------------------------------------
@bp.post("/api/employees")
def create_employee():
    _uid, role = actor()
    require_roles(role, "HRPartner")
    data = body()
    full_name = require_str(data, "full_name")
    email = require_str(data, "email")
    department = require_str(data, "department")
    role_title = require_str(data, "role_title")
    clearance = require_enum(data, "access_clearance", CLEARANCES)
    hired_raw = require_field(data, "hired_at")
    hired_dt = parse_dt(hired_raw)
    if hired_dt is None:
        raise err_invalid_request("hired_at must be an ISO 8601 timestamp")
    for e in all_rows("employees"):
        if e["email"] == email:
            raise err_duplicate_email()
    emp = new_record(
        "employees",
        {
            "full_name": full_name,
            "email": email,
            "department": department,
            "role_title": role_title,
            "access_clearance": clearance,
            "hired_at": hired_raw if isinstance(hired_raw, str) else fmt_ts(hired_dt),
            "_hired_dt": hired_dt,
            "status": "PREBOARDING",
            "departure_type": None,
            "notice_given_at": None,
            "departed_at": None,
            "training_current": False,
        },
    )
    # Onboarding cascades (PRD §3.3): fresh acknowledgment at the current
    # policy version, plus the auto-assigned BASIC_TS training due hired+30d.
    ack_due = add_days(now(), ACK_WINDOW_DAYS)
    new_record(
        "acknowledgments",
        {
            "employee_id": emp["id"],
            "policy_version": program["current_policy_version"],
            "due_at": fmt_ts(ack_due),
            "_due_at_dt": ack_due,
            "signed_at": None,
            "status": "PENDING",
        },
    )
    training_due = add_days(hired_dt, 30)
    new_record(
        "training_assignments",
        {
            "employee_id": emp["id"],
            "module": "BASIC_TS",
            "due_at": fmt_ts(training_due),
            "_due_at_dt": training_due,
            "completed_at": None,
            "status": "ASSIGNED",
        },
    )
    return ok_object(serialize(emp), code=201)


@bp.get("/api/employees")
def list_employees():
    _uid, role = actor()
    require_roles(role, "HRPartner", "IPCounsel", "SecurityOfficer")
    filters = [(f, request.args[f]) for f in ("department", "status", "access_clearance") if f in request.args]
    return _paginate_list("employees", filters)


@bp.get("/api/employees/<rid>")
def get_employee(rid):
    user_id, role = actor()
    require_roles(role, "HRPartner", "IPCounsel", "SecurityOfficer", "Employee")
    emp = by_id("employees", rid)
    if emp is None:
        raise err_not_found("employee not found")
    if role == "Employee" and user_id != rid:
        # Employees read their own record only (SCAFFOLD §1.7).
        raise err_ownership("Employees may read only their own record")
    recompute_training_current(emp)
    return ok_object(serialize(emp))


@bp.post("/api/employees/<rid>/state")
def employee_state(rid):
    _uid, role = actor()
    require_roles(role, "HRPartner")
    emp = by_id("employees", rid)
    if emp is None:
        raise err_not_found("employee not found")
    data = body()
    to_status = require_str(data, "to_status")
    if to_status not in EMPLOYEE_STATUSES:
        raise err_invalid_request(f"to_status must be one of {list(EMPLOYEE_STATUSES)}")
    cur = emp["status"]

    if to_status == "ACTIVE":
        if cur != "PREBOARDING":
            raise err_invalid_state(f"Cannot move employee from {cur} to ACTIVE")
        signed = any(
            a["employee_id"] == emp["id"]
            and a["status"] == "SIGNED"
            and a["policy_version"] == program["current_policy_version"]
            for a in all_rows("acknowledgments")
        )
        if not signed:
            raise err_ack_required()
        emp["status"] = "ACTIVE"
        touch(emp)
    elif to_status == "NOTICE":
        if cur != "ACTIVE":
            raise err_invalid_state(f"Cannot move employee from {cur} to NOTICE")
        departure_type = data.get("departure_type")
        if departure_type not in DEPARTURE_TYPES:
            raise err_invalid_request("departure_type must be VOLUNTARY or INVOLUNTARY")
        emp["status"] = "NOTICE"
        emp["departure_type"] = departure_type
        stamp(emp, "notice_given_at")
        touch(emp)
        if departure_type == "INVOLUNTARY":
            new_record(
                "forensic_reviews",
                {
                    "employee_id": emp["id"],
                    "trigger_reason": "INVOLUNTARY_DEPARTURE",
                    "status": "OPENED",
                    "exfil_indicator_count": 0,
                    "findings_notes": "",
                    "reviewed_by_counsel_id": None,
                },
            )
    elif to_status == "DEPARTED":
        if cur != "NOTICE":
            raise err_invalid_state(f"Cannot move employee from {cur} to DEPARTED")
        certified = any(
            i["employee_id"] == emp["id"] and i["status"] == "CERTIFIED"
            for i in all_rows("exit_interviews")
        )
        if not certified:
            raise err_interview_not_certified()
        active_grants = any(
            g["employee_id"] == emp["id"]
            and g["status"] in ("REQUESTED", "APPROVED", "PROVISIONED", "SUSPENDED")
            for g in all_rows("grants")
        )
        if active_grants:
            raise err_grants_remain("Departure attempted while active grants remain")
        unconcluded = any(
            r["employee_id"] == emp["id"]
            and r["status"] not in ("CLOSED_NO_ACTION", "ESCALATED")
            for r in all_rows("forensic_reviews")
        )
        if unconcluded:
            raise err_review_not_concluded()
        emp["status"] = "DEPARTED"
        stamp(emp, "departed_at")
        touch(emp)
    else:  # PREBOARDING is never a manual target
        raise err_invalid_state(f"Cannot move employee from {cur} to {to_status}")
    return ok_object(serialize(emp))


# ---------------------------------------------------------------------------
# Acknowledgment
# ---------------------------------------------------------------------------
@bp.post("/api/acknowledgments")
def create_acknowledgment():
    _uid, role = actor()
    require_roles(role, "HRPartner")
    data = body()
    employee_id = require_str(data, "employee_id")
    emp = by_id("employees", employee_id)
    if emp is None:
        raise err_not_found("employee not found")
    due = add_days(now(), ACK_WINDOW_DAYS)
    ack = new_record(
        "acknowledgments",
        {
            "employee_id": employee_id,
            "policy_version": program["current_policy_version"],
            "due_at": fmt_ts(due),
            "_due_at_dt": due,
            "signed_at": None,
            "status": "PENDING",
        },
    )
    return ok_object(serialize(ack), code=201)


@bp.get("/api/acknowledgments")
def list_acknowledgments():
    _uid, role = actor()
    require_roles(role, "HRPartner", "IPCounsel", "Employee")
    filters = [(f, request.args[f]) for f in ("employee_id", "status", "policy_version") if f in request.args]
    return _paginate_list("acknowledgments", filters)


@bp.get("/api/acknowledgments/<rid>")
def get_acknowledgment(rid):
    _uid, role = actor()
    require_roles(role, "HRPartner", "IPCounsel", "Employee")
    ack = by_id("acknowledgments", rid)
    if ack is None:
        raise err_not_found("acknowledgment not found")
    return ok_object(serialize(ack))


@bp.post("/api/acknowledgments/<rid>/sign")
def sign_acknowledgment(rid):
    user_id, role = actor()
    require_roles(role, "Employee")
    ack = by_id("acknowledgments", rid)
    if ack is None:
        raise err_not_found("acknowledgment not found")
    # Ownership (priority 3) before state (6) and policy-currency (9).
    if user_id != ack["employee_id"]:
        raise err_ownership("Employees sign only their own acknowledgment")
    if ack["status"] != "PENDING":
        raise err_invalid_state(f"Cannot sign acknowledgment in {ack['status']}")
    if ack["policy_version"] != program["current_policy_version"]:
        raise err_policy_stale()
    ack["status"] = "SIGNED"
    stamp(ack, "signed_at")
    touch(ack)
    return ok_object(serialize(ack))


# ---------------------------------------------------------------------------
# ExitInterview
# ---------------------------------------------------------------------------
def _interview_overlap(employee_id, start_dt, end_dt, exclude_id=None):
    """Half-open [start, end) overlap against the employee's other SCHEDULED or
    CONDUCTED interviews; starting exactly when another ends is permitted."""
    for iv in all_rows("exit_interviews"):
        if iv["employee_id"] != employee_id:
            continue
        if exclude_id is not None and iv["id"] == exclude_id:
            continue
        if iv["status"] not in ("SCHEDULED", "CONDUCTED"):
            continue
        if start_dt < iv["_scheduled_end_dt"] and iv["_scheduled_start_dt"] < end_dt:
            raise err_interview_overlap()


@bp.post("/api/exit-interviews")
def create_exit_interview():
    _uid, role = actor()
    require_roles(role, "HRPartner")
    data = body()
    employee_id = require_str(data, "employee_id")
    emp = by_id("employees", employee_id)
    if emp is None:
        raise err_not_found("employee not found")
    # Referenced-entity state gate (cat 6) before temporal rules (cat 8).
    if emp["status"] not in ("ACTIVE", "NOTICE"):
        raise err_invalid_state("Employee must be ACTIVE or NOTICE for an exit interview")
    start_raw = require_field(data, "scheduled_start")
    end_raw = require_field(data, "scheduled_end")
    start_dt = parse_dt(start_raw)
    end_dt = parse_dt(end_raw)
    if start_dt is None or end_dt is None:
        raise err_invalid_request("scheduled_start / scheduled_end must be ISO 8601 timestamps")
    if end_dt <= start_dt:
        raise err_date_order("scheduled_end must be strictly after scheduled_start")
    _interview_overlap(employee_id, start_dt, end_dt)
    rec = new_record(
        "exit_interviews",
        {
            "employee_id": employee_id,
            "scheduled_start": start_raw if isinstance(start_raw, str) else fmt_ts(start_dt),
            "scheduled_end": end_raw if isinstance(end_raw, str) else fmt_ts(end_dt),
            "_scheduled_start_dt": start_dt,
            "_scheduled_end_dt": end_dt,
            "conducted_at": None,
            "return_certification": False,
            "obligations_reiterated": False,
            "no_show_count": 0,
            "status": "SCHEDULED",
        },
    )
    return ok_object(serialize(rec), code=201)


@bp.get("/api/exit-interviews")
def list_exit_interviews():
    _uid, role = actor()
    require_roles(role, "HRPartner", "IPCounsel")
    filters = [(f, request.args[f]) for f in ("employee_id", "status") if f in request.args]
    return _paginate_list("exit_interviews", filters)


@bp.get("/api/exit-interviews/<rid>")
def get_exit_interview(rid):
    _uid, role = actor()
    require_roles(role, "HRPartner", "IPCounsel")
    iv = by_id("exit_interviews", rid)
    if iv is None:
        raise err_not_found("exit interview not found")
    return ok_object(serialize(iv))


@bp.patch("/api/exit-interviews/<rid>")
def patch_exit_interview(rid):
    """Record the two certification flags; the interview must not be terminal."""
    _uid, role = actor()
    require_roles(role, "HRPartner")
    iv = by_id("exit_interviews", rid)
    if iv is None:
        raise err_not_found("exit interview not found")
    if iv["status"] in ("CERTIFIED", "CANCELLED"):
        raise err_invalid_state(f"Cannot update interview in {iv['status']}")
    data = body()
    if "return_certification" in data and data["return_certification"] is not None:
        if not isinstance(data["return_certification"], bool):
            raise err_invalid_request("return_certification must be a boolean")
        iv["return_certification"] = data["return_certification"]
    if "obligations_reiterated" in data and data["obligations_reiterated"] is not None:
        if not isinstance(data["obligations_reiterated"], bool):
            raise err_invalid_request("obligations_reiterated must be a boolean")
        iv["obligations_reiterated"] = data["obligations_reiterated"]
    touch(iv)
    return ok_object(serialize(iv))


@bp.post("/api/exit-interviews/<rid>/state")
def exit_interview_state(rid):
    _uid, role = actor()
    require_roles(role, "HRPartner")
    iv = by_id("exit_interviews", rid)
    if iv is None:
        raise err_not_found("exit interview not found")
    data = body()
    to_status = require_str(data, "to_status")
    if to_status not in INTERVIEW_STATUSES:
        raise err_invalid_request(f"to_status must be one of {list(INTERVIEW_STATUSES)}")
    cur = iv["status"]

    if to_status == "CONDUCTED":
        if cur != "SCHEDULED":
            raise err_invalid_state(f"Cannot move interview from {cur} to CONDUCTED")
        iv["status"] = "CONDUCTED"
        stamp(iv, "conducted_at")
        touch(iv)
    elif to_status == "NO_SHOW":
        if cur != "SCHEDULED":
            raise err_invalid_state(f"Cannot move interview from {cur} to NO_SHOW")
        iv["status"] = "NO_SHOW"
        iv["no_show_count"] += 1
        touch(iv)
    elif to_status == "SCHEDULED":
        if cur != "NO_SHOW":
            raise err_invalid_state(f"Cannot move interview from {cur} to SCHEDULED")
        start_raw = require_field(data, "scheduled_start")
        end_raw = require_field(data, "scheduled_end")
        start_dt = parse_dt(start_raw)
        end_dt = parse_dt(end_raw)
        if start_dt is None or end_dt is None:
            raise err_invalid_request("scheduled_start / scheduled_end must be ISO 8601 timestamps")
        if end_dt <= start_dt:
            raise err_date_order("scheduled_end must be strictly after scheduled_start")
        _interview_overlap(iv["employee_id"], start_dt, end_dt, exclude_id=iv["id"])
        iv["scheduled_start"] = start_raw if isinstance(start_raw, str) else fmt_ts(start_dt)
        iv["scheduled_end"] = end_raw if isinstance(end_raw, str) else fmt_ts(end_dt)
        iv["_scheduled_start_dt"] = start_dt
        iv["_scheduled_end_dt"] = end_dt
        iv["status"] = "SCHEDULED"
        touch(iv)
    elif to_status == "ESCALATED":
        if cur != "NO_SHOW":
            raise err_invalid_state(f"Cannot move interview from {cur} to ESCALATED")
        if iv["no_show_count"] < 2:
            raise err_invalid_state("ESCALATED requires no_show_count >= 2")
        iv["status"] = "ESCALATED"
        touch(iv)
    elif to_status == "CERTIFIED":
        if cur != "CONDUCTED":
            raise err_invalid_state(f"Cannot move interview from {cur} to CERTIFIED")
        if not (iv["return_certification"] and iv["obligations_reiterated"]):
            raise err_invalid_request(
                "CERTIFIED requires return_certification and obligations_reiterated"
            )
        iv["status"] = "CERTIFIED"
        touch(iv)
    elif to_status == "CANCELLED":
        if cur not in ("SCHEDULED", "NO_SHOW"):
            raise err_invalid_state(f"Cannot move interview from {cur} to CANCELLED")
        iv["status"] = "CANCELLED"
        touch(iv)
    return ok_object(serialize(iv))


# ---------------------------------------------------------------------------
# TrainingAssignment
# ---------------------------------------------------------------------------
@bp.post("/api/training-assignments")
def create_training():
    _uid, role = actor()
    require_roles(role, "HRPartner")
    data = body()
    employee_id = require_str(data, "employee_id")
    emp = by_id("employees", employee_id)
    if emp is None:
        raise err_not_found("employee not found")
    module = require_enum(data, "module", TRAINING_MODULES)
    due_raw = require_field(data, "due_at")
    due_dt = parse_dt(due_raw)
    if due_dt is None:
        raise err_invalid_request("due_at must be an ISO 8601 timestamp")
    rec = new_record(
        "training_assignments",
        {
            "employee_id": employee_id,
            "module": module,
            "due_at": due_raw if isinstance(due_raw, str) else fmt_ts(due_dt),
            "_due_at_dt": due_dt,
            "completed_at": None,
            "status": "ASSIGNED",
        },
    )
    recompute_training_current(emp)
    return ok_object(serialize(rec), code=201)


@bp.get("/api/training-assignments")
def list_training():
    _uid, role = actor()
    require_roles(role, "HRPartner", "IPCounsel", "Employee")
    filters = [(f, request.args[f]) for f in ("employee_id", "module", "status") if f in request.args]
    return _paginate_list("training_assignments", filters)


@bp.get("/api/training-assignments/<rid>")
def get_training(rid):
    _uid, role = actor()
    require_roles(role, "HRPartner", "IPCounsel", "Employee")
    t = by_id("training_assignments", rid)
    if t is None:
        raise err_not_found("training assignment not found")
    return ok_object(serialize(t))


@bp.post("/api/training-assignments/<rid>/state")
def training_state(rid):
    user_id, role = actor()
    require_roles(role, "Employee", "HRPartner")
    t = by_id("training_assignments", rid)
    if t is None:
        raise err_not_found("training assignment not found")
    data = body()
    to_status = require_str(data, "to_status")
    if to_status not in TRAINING_STATUSES:
        raise err_invalid_request(f"to_status must be one of {list(TRAINING_STATUSES)}")
    cur = t["status"]
    emp = by_id("employees", t["employee_id"])

    if to_status == "COMPLETED":
        if role != "Employee":
            raise err_unauthorized_role("COMPLETED requires the Employee role")
        if user_id != t["employee_id"]:
            raise err_ownership("Employees complete only their own training")
        if cur not in ("ASSIGNED", "OVERDUE", "ESCALATED"):
            raise err_invalid_state(f"Cannot move training from {cur} to COMPLETED")
        t["status"] = "COMPLETED"
        stamp(t, "completed_at")
        touch(t)
    elif to_status == "ESCALATED":
        if role != "HRPartner":
            raise err_unauthorized_role("ESCALATED requires HRPartner")
        if cur != "OVERDUE":
            raise err_invalid_state(f"Cannot move training from {cur} to ESCALATED")
        t["status"] = "ESCALATED"
        touch(t)
    elif to_status == "EXCUSED":
        if role != "HRPartner":
            raise err_unauthorized_role("EXCUSED requires HRPartner")
        if cur not in ("ASSIGNED", "OVERDUE"):
            raise err_invalid_state(f"Cannot move training from {cur} to EXCUSED")
        t["status"] = "EXCUSED"
        touch(t)
    else:  # ASSIGNED / OVERDUE are not manual targets
        raise err_invalid_state(f"Cannot move training from {cur} to {to_status}")
    if emp is not None:
        recompute_training_current(emp)
    return ok_object(serialize(t))
