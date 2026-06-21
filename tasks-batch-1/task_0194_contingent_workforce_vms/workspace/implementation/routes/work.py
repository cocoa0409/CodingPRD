"""Timesheet, Expense, StatementOfWork, Milestone routes."""
from flask import Blueprint, request

import db
import services
from errors import err
from middleware import get_user_context, require_role, get_json_body, parse_iso
from response import success
from serializers import public
from listing import paginate, filter_by
import validators as V

bp = Blueprint("work", __name__)

EXPENSE_CATEGORIES = {"TRAVEL", "LODGING", "MEALS", "EQUIPMENT", "OTHER"}


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _supplier_of_assignment(assignment):
    """The supplier id that owns a given assignment, via its originating submittal."""
    sub = db.submittals.get(assignment["submittal_id"])
    if sub is None:
        return None
    return sub["supplier_id"]


# ============================= Timesheet ===================================

@bp.route("/vms/timesheets", methods=["POST"])
def create_timesheet():
    user_id, role = get_user_context()
    require_role(role, ["Supplier"])
    body = get_json_body()
    assignment_id = V.as_string(V.require_present(body, "assignment_id"), "assignment_id")
    assignment = db.assignments.get(assignment_id)
    if assignment is None:
        raise err("ERR_NOT_FOUND", "Assignment not found")

    # Ownership: acting supplier must own the assignment.
    owner = _supplier_of_assignment(assignment)
    if user_id != owner:
        raise err("ERR_NOT_RESOURCE_OWNER", "Supplier does not own this assignment")

    week_raw = V.as_string(V.require_present(body, "week_start_date"), "week_start_date")
    week_dt = parse_iso(week_raw, "week_start_date")
    regular_hours = V.hours_in_range(V.require_present(body, "regular_hours"), "regular_hours")
    overtime_hours = 0
    if body.get("overtime_hours") is not None:
        overtime_hours = V.hours_in_range(body["overtime_hours"], "overtime_hours")

    week_iso = _iso(week_dt)
    # Duplicate-week (priority 16): exact match on week_start_date for the assignment.
    for ts in db.timesheets.values():
        if ts["assignment_id"] == assignment_id and ts["week_start_date"] == week_iso:
            raise err("ERR_DUPLICATE_WEEK", "A timesheet already exists for this week")

    record = db.common_fields()
    record.update({
        "assignment_id": assignment_id,
        "week_start_date": week_iso,
        "regular_hours": regular_hours,
        "overtime_hours": overtime_hours,
        "submitted_at": None,
        "bill_amount_cents": 0,
        "pay_amount_cents": 0,
        "status": "DRAFT",
    })
    db.timesheets[record["id"]] = record
    return success(public(record), 201)


@bp.route("/vms/timesheets/<tid>", methods=["GET"])
def get_timesheet(tid):
    get_user_context()
    ts = db.timesheets.get(tid)
    if ts is None:
        raise err("ERR_NOT_FOUND", "Timesheet not found")
    return success(public(ts), 200)


@bp.route("/vms/timesheets", methods=["GET"])
def list_timesheets():
    get_user_context()
    records = filter_by(list(db.timesheets.values()),
                        assignment_id=request.args.get("assignment_id"),
                        status=request.args.get("status"))
    data, pagination = paginate(records)
    return success(data, 200, "array", pagination)


def _load_timesheet(tid):
    ts = db.timesheets.get(tid)
    if ts is None:
        raise err("ERR_NOT_FOUND", "Timesheet not found")
    return ts


def _check_supplier_owns_timesheet(user_id, role, ts):
    if role == "Supplier":
        assignment = db.assignments.get(ts["assignment_id"])
        owner = _supplier_of_assignment(assignment) if assignment else None
        if user_id != owner:
            raise err("ERR_NOT_RESOURCE_OWNER", "Supplier does not own this timesheet")


@bp.route("/vms/timesheets/<tid>/submit", methods=["POST"])
def submit_timesheet(tid):
    user_id, role = get_user_context()
    require_role(role, ["Supplier"])
    ts = _load_timesheet(tid)
    _check_supplier_owns_timesheet(user_id, role, ts)
    if ts["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Timesheet is not DRAFT")
    assignment = db.assignments[ts["assignment_id"]]
    if assignment["engagement_status"] != "ACTIVE":
        raise err("ERR_ASSIGNMENT_NOT_ACTIVE", "Assignment is not ACTIVE")
    if (ts["regular_hours"] + ts["overtime_hours"]) <= 0:
        raise err("ERR_EMPTY_TIMESHEET", "Timesheet has no reported hours")
    program = db.programs[assignment["program_id"]]
    ts["submitted_at"] = program["current_clock"]
    ts["status"] = "SUBMITTED"
    db.touch(ts)
    return success(public(ts), 200)


@bp.route("/vms/timesheets/<tid>/approve", methods=["POST"])
def approve_timesheet(tid):
    _, role = get_user_context()
    require_role(role, ["HiringManager"])
    ts = _load_timesheet(tid)
    if ts["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Timesheet is not SUBMITTED")
    assignment = db.assignments[ts["assignment_id"]]
    services._approve_timesheet(ts, assignment)
    return success(public(ts), 200)


@bp.route("/vms/timesheets/<tid>/reject", methods=["POST"])
def reject_timesheet(tid):
    _, role = get_user_context()
    require_role(role, ["HiringManager"])
    ts = _load_timesheet(tid)
    if ts["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Timesheet is not SUBMITTED")
    ts["status"] = "REJECTED"
    db.touch(ts)
    return success(public(ts), 200)


@bp.route("/vms/timesheets/<tid>/reopen", methods=["POST"])
def reopen_timesheet(tid):
    user_id, role = get_user_context()
    require_role(role, ["Supplier"])
    ts = _load_timesheet(tid)
    _check_supplier_owns_timesheet(user_id, role, ts)
    if ts["status"] != "REJECTED":
        raise err("ERR_INVALID_STATE", "Timesheet is not REJECTED")
    ts["status"] = "DRAFT"
    ts["submitted_at"] = None
    db.touch(ts)
    return success(public(ts), 200)


@bp.route("/vms/timesheets/<tid>/invoice", methods=["POST"])
def invoice_timesheet(tid):
    _, role = get_user_context()
    require_role(role, ["Finance"])
    ts = _load_timesheet(tid)
    if ts["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Timesheet is not APPROVED")
    ts["status"] = "INVOICED"
    db.touch(ts)
    return success(public(ts), 200)


# ============================= Expense =====================================

@bp.route("/vms/expenses", methods=["POST"])
def create_expense():
    user_id, role = get_user_context()
    require_role(role, ["Supplier"])
    body = get_json_body()
    assignment_id = V.as_string(V.require_present(body, "assignment_id"), "assignment_id")
    assignment = db.assignments.get(assignment_id)
    if assignment is None:
        raise err("ERR_NOT_FOUND", "Assignment not found")
    owner = _supplier_of_assignment(assignment)
    if user_id != owner:
        raise err("ERR_NOT_RESOURCE_OWNER", "Supplier does not own this assignment")

    category = V.require_present(body, "category")
    V.enum_member(category, "category", EXPENSE_CATEGORIES)
    amount = V.as_int(V.require_present(body, "amount_cents"), "amount_cents")
    if amount < 1:
        raise err("ERR_INVALID_REQUEST", "amount_cents must be >= 1")
    billable = True
    if body.get("billable") is not None:
        billable = V.as_bool(body["billable"], "billable")

    record = db.common_fields()
    record.update({
        "assignment_id": assignment_id,
        "category": category,
        "amount_cents": amount,
        "billable": billable,
        "reimbursable_amount_cents": 0,
        "status": "DRAFT",
    })
    db.expenses[record["id"]] = record
    return success(public(record), 201)


@bp.route("/vms/expenses/<eid>", methods=["GET"])
def get_expense(eid):
    get_user_context()
    ex = db.expenses.get(eid)
    if ex is None:
        raise err("ERR_NOT_FOUND", "Expense not found")
    return success(public(ex), 200)


@bp.route("/vms/expenses", methods=["GET"])
def list_expenses():
    get_user_context()
    records = filter_by(list(db.expenses.values()),
                        assignment_id=request.args.get("assignment_id"),
                        status=request.args.get("status"),
                        category=request.args.get("category"))
    data, pagination = paginate(records)
    return success(data, 200, "array", pagination)


def _load_expense(eid):
    ex = db.expenses.get(eid)
    if ex is None:
        raise err("ERR_NOT_FOUND", "Expense not found")
    return ex


def _check_supplier_owns_expense(user_id, role, ex):
    if role == "Supplier":
        assignment = db.assignments.get(ex["assignment_id"])
        owner = _supplier_of_assignment(assignment) if assignment else None
        if user_id != owner:
            raise err("ERR_NOT_RESOURCE_OWNER", "Supplier does not own this expense")


@bp.route("/vms/expenses/<eid>/submit", methods=["POST"])
def submit_expense(eid):
    user_id, role = get_user_context()
    require_role(role, ["Supplier"])
    ex = _load_expense(eid)
    _check_supplier_owns_expense(user_id, role, ex)
    if ex["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Expense is not DRAFT")
    assignment = db.assignments[ex["assignment_id"]]
    if assignment["engagement_status"] != "ACTIVE":
        raise err("ERR_ASSIGNMENT_NOT_ACTIVE", "Assignment is not ACTIVE")
    ex["status"] = "SUBMITTED"
    db.touch(ex)
    return success(public(ex), 200)


@bp.route("/vms/expenses/<eid>/approve", methods=["POST"])
def approve_expense(eid):
    _, role = get_user_context()
    require_role(role, ["HiringManager"])
    ex = _load_expense(eid)
    if ex["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Expense is not SUBMITTED")
    ex["reimbursable_amount_cents"] = services.expense_reimbursement(ex["category"], ex["amount_cents"])
    ex["status"] = "APPROVED"
    db.touch(ex)
    return success(public(ex), 200)


@bp.route("/vms/expenses/<eid>/reject", methods=["POST"])
def reject_expense(eid):
    _, role = get_user_context()
    require_role(role, ["HiringManager"])
    ex = _load_expense(eid)
    if ex["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Expense is not SUBMITTED")
    ex["status"] = "REJECTED"
    db.touch(ex)
    return success(public(ex), 200)


@bp.route("/vms/expenses/<eid>/reopen", methods=["POST"])
def reopen_expense(eid):
    user_id, role = get_user_context()
    require_role(role, ["Supplier"])
    ex = _load_expense(eid)
    _check_supplier_owns_expense(user_id, role, ex)
    if ex["status"] != "REJECTED":
        raise err("ERR_INVALID_STATE", "Expense is not REJECTED")
    ex["status"] = "DRAFT"
    db.touch(ex)
    return success(public(ex), 200)


@bp.route("/vms/expenses/<eid>/invoice", methods=["POST"])
def invoice_expense(eid):
    _, role = get_user_context()
    require_role(role, ["Finance"])
    ex = _load_expense(eid)
    if ex["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Expense is not APPROVED")
    ex["status"] = "INVOICED"
    db.touch(ex)
    return success(public(ex), 200)


# ============================= StatementOfWork =============================

@bp.route("/vms/statements-of-work", methods=["POST"])
def create_sow():
    _, role = get_user_context()
    require_role(role, ["ProgramManager"])
    body = get_json_body()
    program_id = V.as_string(V.require_present(body, "program_id"), "program_id")
    program = db.programs.get(program_id)
    if program is None:
        raise err("ERR_NOT_FOUND", "Program not found")
    supplier_id = V.as_string(V.require_present(body, "supplier_id"), "supplier_id")
    supplier = db.suppliers.get(supplier_id)
    if supplier is None:
        raise err("ERR_NOT_FOUND", "Supplier not found")
    title = V.as_string(V.require_present(body, "title"), "title")
    total_value = V.as_int(V.require_present(body, "total_value_cents"), "total_value_cents")
    if total_value < 1:
        raise err("ERR_INVALID_REQUEST", "total_value_cents must be >= 1")

    record = db.common_fields()
    record.update({
        "program_id": program_id,
        "supplier_id": supplier_id,
        "title": title,
        "total_value_cents": total_value,
        "invoiced_value_cents": 0,
        "status": "DRAFT",
    })
    db.statements_of_work[record["id"]] = record
    return success(public(record), 201)


@bp.route("/vms/statements-of-work/<sid>", methods=["GET"])
def get_sow(sid):
    get_user_context()
    sow = db.statements_of_work.get(sid)
    if sow is None:
        raise err("ERR_NOT_FOUND", "SOW not found")
    return success(public(sow), 200)


@bp.route("/vms/statements-of-work", methods=["GET"])
def list_sows():
    get_user_context()
    records = filter_by(list(db.statements_of_work.values()),
                        program_id=request.args.get("program_id"),
                        supplier_id=request.args.get("supplier_id"),
                        status=request.args.get("status"))
    data, pagination = paginate(records)
    return success(data, 200, "array", pagination)


def _load_sow(sid):
    sow = db.statements_of_work.get(sid)
    if sow is None:
        raise err("ERR_NOT_FOUND", "SOW not found")
    return sow


def _sow_milestones(sow_id):
    return [m for m in db.milestones.values() if m["statement_of_work_id"] == sow_id]


@bp.route("/vms/statements-of-work/<sid>/activate", methods=["POST"])
def activate_sow(sid):
    _, role = get_user_context()
    require_role(role, ["ProgramManager"])
    sow = _load_sow(sid)
    if sow["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "SOW is not DRAFT")
    program = db.programs[sow["program_id"]]
    if program["status"] != "ACTIVE":
        raise err("ERR_PROGRAM_NOT_ACTIVE", "Program is not ACTIVE")
    supplier = db.suppliers.get(sow["supplier_id"])
    if supplier is None or supplier["program_id"] != sow["program_id"] or supplier["status"] != "ACTIVE":
        raise err("ERR_SUPPLIER_NOT_ELIGIBLE", "Supplier is not eligible")
    milestones = _sow_milestones(sid)
    if len(milestones) == 0:
        raise err("ERR_SOW_NO_MILESTONES", "SOW has no milestones")
    total = sum(m["milestone_amount_cents"] for m in milestones)
    if total > sow["total_value_cents"]:
        raise err("ERR_SOW_VALUE_EXCEEDED", "Sum of milestones exceeds SOW total value")
    sow["status"] = "ACTIVE"
    db.touch(sow)
    return success(public(sow), 200)


@bp.route("/vms/statements-of-work/<sid>/close", methods=["POST"])
def close_sow(sid):
    _, role = get_user_context()
    require_role(role, ["ProgramManager"])
    sow = _load_sow(sid)
    if sow["status"] not in ("ACTIVE", "COMPLETED"):
        raise err("ERR_INVALID_STATE", "SOW cannot be closed from its current state")
    if sow["status"] == "ACTIVE":
        for m in _sow_milestones(sid):
            if m["status"] == "SUBMITTED":
                raise err("ERR_OPEN_APPROVALS_PENDING", "A submitted milestone awaits acceptance")
    sow["status"] = "CLOSED"
    db.touch(sow)
    return success(public(sow), 200)


@bp.route("/vms/statements-of-work/<sid>/cancel", methods=["POST"])
def cancel_sow(sid):
    _, role = get_user_context()
    require_role(role, ["ProgramManager"])
    sow = _load_sow(sid)
    if sow["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT SOW can be cancelled")
    sow["status"] = "CANCELLED"
    db.touch(sow)
    return success(public(sow), 200)


# ============================= Milestone ===================================

@bp.route("/vms/milestones", methods=["POST"])
def create_milestone():
    _, role = get_user_context()
    require_role(role, ["ProgramManager"])
    body = get_json_body()
    sow_id = V.as_string(V.require_present(body, "statement_of_work_id"), "statement_of_work_id")
    sow = db.statements_of_work.get(sow_id)
    if sow is None:
        raise err("ERR_NOT_FOUND", "SOW not found")
    name = V.as_string(V.require_present(body, "name"), "name")
    amount = V.as_int(V.require_present(body, "milestone_amount_cents"), "milestone_amount_cents")
    if amount < 1:
        raise err("ERR_INVALID_REQUEST", "milestone_amount_cents must be >= 1")
    sequence = V.as_int(V.require_present(body, "sequence"), "sequence")
    if sequence < 1:
        raise err("ERR_INVALID_REQUEST", "sequence must be >= 1")

    record = db.common_fields()
    record.update({
        "statement_of_work_id": sow_id,
        "name": name,
        "milestone_amount_cents": amount,
        "sequence": sequence,
        "status": "PENDING",
    })
    db.milestones[record["id"]] = record
    return success(public(record), 201)


@bp.route("/vms/milestones/<mid>", methods=["GET"])
def get_milestone(mid):
    get_user_context()
    m = db.milestones.get(mid)
    if m is None:
        raise err("ERR_NOT_FOUND", "Milestone not found")
    return success(public(m), 200)


@bp.route("/vms/milestones", methods=["GET"])
def list_milestones():
    get_user_context()
    records = filter_by(list(db.milestones.values()),
                        statement_of_work_id=request.args.get("statement_of_work_id"),
                        status=request.args.get("status"))
    data, pagination = paginate(records)
    return success(data, 200, "array", pagination)


def _load_milestone(mid):
    m = db.milestones.get(mid)
    if m is None:
        raise err("ERR_NOT_FOUND", "Milestone not found")
    return m


def _check_supplier_owns_milestone(user_id, role, milestone):
    if role == "Supplier":
        sow = db.statements_of_work.get(milestone["statement_of_work_id"])
        owner = sow["supplier_id"] if sow else None
        if user_id != owner:
            raise err("ERR_NOT_RESOURCE_OWNER", "Supplier does not own this milestone")


@bp.route("/vms/milestones/<mid>/start", methods=["POST"])
def start_milestone(mid):
    user_id, role = get_user_context()
    require_role(role, ["Supplier"])
    m = _load_milestone(mid)
    _check_supplier_owns_milestone(user_id, role, m)
    if m["status"] not in ("PENDING", "REJECTED"):
        raise err("ERR_INVALID_STATE", "Milestone cannot be started from its current state")
    sow = db.statements_of_work[m["statement_of_work_id"]]
    if sow["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "SOW is not ACTIVE")
    m["status"] = "IN_PROGRESS"
    db.touch(m)
    return success(public(m), 200)


@bp.route("/vms/milestones/<mid>/submit", methods=["POST"])
def submit_milestone(mid):
    user_id, role = get_user_context()
    require_role(role, ["Supplier"])
    m = _load_milestone(mid)
    _check_supplier_owns_milestone(user_id, role, m)
    if m["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Milestone is not IN_PROGRESS")
    # Sequence: all lower-sequence milestones must be ACCEPTED or INVOICED.
    for other in _sow_milestones(m["statement_of_work_id"]):
        if other["sequence"] < m["sequence"] and other["status"] not in ("ACCEPTED", "INVOICED"):
            raise err("ERR_MILESTONE_SEQUENCE_VIOLATION",
                      "A lower-sequence milestone is not yet ACCEPTED/INVOICED")
    m["status"] = "SUBMITTED"
    db.touch(m)
    return success(public(m), 200)


@bp.route("/vms/milestones/<mid>/accept", methods=["POST"])
def accept_milestone(mid):
    _, role = get_user_context()
    require_role(role, ["HiringManager"])
    m = _load_milestone(mid)
    if m["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Milestone is not SUBMITTED")
    sow = db.statements_of_work[m["statement_of_work_id"]]
    accepted_sum = sum(o["milestone_amount_cents"] for o in _sow_milestones(sow["id"])
                       if o["status"] == "ACCEPTED")
    projected = sow["invoiced_value_cents"] + accepted_sum + m["milestone_amount_cents"]
    if projected > sow["total_value_cents"]:
        raise err("ERR_SOW_VALUE_EXCEEDED", "Accepting would exceed SOW not-to-exceed value")
    m["status"] = "ACCEPTED"
    db.touch(m)
    return success(public(m), 200)


@bp.route("/vms/milestones/<mid>/reject", methods=["POST"])
def reject_milestone(mid):
    _, role = get_user_context()
    require_role(role, ["HiringManager"])
    m = _load_milestone(mid)
    if m["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Milestone is not SUBMITTED")
    m["status"] = "REJECTED"
    db.touch(m)
    return success(public(m), 200)


@bp.route("/vms/milestones/<mid>/invoice", methods=["POST"])
def invoice_milestone(mid):
    _, role = get_user_context()
    require_role(role, ["Finance"])
    m = _load_milestone(mid)
    if m["status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE", "Milestone is not ACCEPTED")
    sow = db.statements_of_work[m["statement_of_work_id"]]
    m["status"] = "INVOICED"
    db.touch(m)
    sow["invoiced_value_cents"] += m["milestone_amount_cents"]
    db.touch(sow)
    # Bubble-up: if every milestone is INVOICED, drive SOW ACTIVE -> COMPLETED.
    all_milestones = _sow_milestones(sow["id"])
    if all_milestones and all(o["status"] == "INVOICED" for o in all_milestones):
        if sow["status"] == "ACTIVE":
            sow["status"] = "COMPLETED"
            db.touch(sow)
    return success(public(m), 200)
