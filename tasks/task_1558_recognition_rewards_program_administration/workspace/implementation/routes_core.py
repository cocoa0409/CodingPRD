"""Routes: programs, departments, employees, budgets.

Every handler runs the PRD section 2.8 pipeline in priority order:
auth -> role/ownership -> existence -> schema -> state -> OCC -> program gate
-> standing -> velocity -> self-dealing -> scope -> duplicates -> temporal ->
inventory -> restricted cap -> capacity -> balance -> fiscal integrity.
"""
from datetime import timedelta

import db
import serialize as ser
import services as svc
from db import now, touch
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_STALE_VERSION, ERR_PROGRAM_NOT_ACTIVE, ERR_NOT_FOUND,
    ERR_BUDGET_PERIOD_OVERLAP, ERR_BUDGET_CLOSED, ERR_BUDGET_NOT_FOUND,
    ERR_BUDGET_EXHAUSTED, ERR_FORBIDDEN_FOR_ROLE,
)
from flask import Blueprint, request
from response import success, success_list
from validate import (
    auth_context, require_role, get_or_404, body, req_str, opt_str, req_int,
    opt_int, req_num, opt_bool, req_enum, parse_iso_date, pagination_params,
)

bp = Blueprint("core", __name__)

READ_ROLES = ["HRAdmin", "FinanceAdmin", "PayrollSpecialist", "Manager",
              "Employee", "VendorOps"]


def _sorted_rows(store):
    """List-endpoint default ordering: created_at ascending (insertion order
    breaks exact ties)."""
    rows = list(store)
    rows.sort(key=lambda e: e["created_at"])
    return rows


def _paginate(rows, serializer):
    limit, offset = pagination_params()
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([serializer(r) for r in page], total, limit, offset)


def _validate_milestones(value):
    if not isinstance(value, list):
        raise_err(ERR_INVALID_REQUEST, "anniversary_milestones must be an array")
    for row in value:
        if not isinstance(row, dict):
            raise_err(ERR_INVALID_REQUEST,
                      "anniversary_milestones entries must be objects")
        years = row.get("years")
        points = row.get("points")
        if not isinstance(years, int) or isinstance(years, bool) \
                or not isinstance(points, int) or isinstance(points, bool):
            raise_err(ERR_INVALID_REQUEST,
                      "anniversary_milestones entries need integer years/points")
    return value


def _validate_state_rate_map(value):
    if not isinstance(value, dict):
        raise_err(ERR_INVALID_REQUEST, "state_rate_map must be an object")
    for k, v in value.items():
        if not isinstance(k, str) or not isinstance(v, (int, float)) \
                or isinstance(v, bool):
            raise_err(ERR_INVALID_REQUEST, "state_rate_map values must be numbers")
    return value


def _apply_program_fields(p, b, partial):
    """Validate and apply program config fields (create: all required core;
    PATCH: only provided keys)."""
    def has(k):
        return k in b

    if not partial or has("name"):
        p["name"] = req_str(b, "name")
    if not partial or has("max_points_per_nomination"):
        v = req_int(b, "max_points_per_nomination")
        if v <= 0:
            raise_err(ERR_INVALID_REQUEST, "max_points_per_nomination must be > 0")
        p["max_points_per_nomination"] = v
    if not partial or has("point_cost_rate_cents"):
        v = req_num(b, "point_cost_rate_cents")
        if v <= 0:
            raise_err(ERR_INVALID_REQUEST, "point_cost_rate_cents must be > 0")
        p["point_cost_rate_cents"] = v
    if not partial or has("state_rate_map"):
        p["state_rate_map"] = _validate_state_rate_map(b.get("state_rate_map"))
    if has("peer_nomination_enabled"):
        p["peer_nomination_enabled"] = opt_bool(b, "peer_nomination_enabled")
    elif not partial:
        p["peer_nomination_enabled"] = True
    if has("manager_nomination_enabled"):
        p["manager_nomination_enabled"] = opt_bool(b, "manager_nomination_enabled")
    elif not partial:
        p["manager_nomination_enabled"] = True
    if has("grossup_enabled"):
        p["grossup_enabled"] = opt_bool(b, "grossup_enabled")
    elif not partial:
        p["grossup_enabled"] = False
    if has("anniversary_milestones"):
        p["anniversary_milestones"] = _validate_milestones(b.get("anniversary_milestones"))
    elif not partial:
        p["anniversary_milestones"] = []
    if has("nomination_review_sla_days"):
        v = opt_int(b, "nomination_review_sla_days")
        if v is None or v <= 0:
            raise_err(ERR_INVALID_REQUEST,
                      "nomination_review_sla_days must be a positive integer")
        p["nomination_review_sla_days"] = v
    elif not partial:
        p["nomination_review_sla_days"] = 14
    if has("duplicate_window_days"):
        v = opt_int(b, "duplicate_window_days")
        if v is None or v < 0:
            raise_err(ERR_INVALID_REQUEST,
                      "duplicate_window_days must be a non-negative integer")
        p["duplicate_window_days"] = v
    elif not partial:
        p["duplicate_window_days"] = 30
    if has("velocity_limit_per_7_days"):
        v = opt_int(b, "velocity_limit_per_7_days")
        if v is None or v <= 0:
            raise_err(ERR_INVALID_REQUEST,
                      "velocity_limit_per_7_days must be a positive integer")
        p["velocity_limit_per_7_days"] = v
    elif not partial:
        p["velocity_limit_per_7_days"] = 5
    if has("accrual_method"):
        p["accrual_method"] = req_enum(
            b, "accrual_method", {"STRAIGHT_LINE", "UTILIZATION_WEIGHTED"})
    elif not partial:
        p["accrual_method"] = "STRAIGHT_LINE"
    if not partial:
        if has("fiscal_year_start_month"):
            v = opt_int(b, "fiscal_year_start_month")
            if v is None or v < 1 or v > 12:
                raise_err(ERR_INVALID_REQUEST,
                          "fiscal_year_start_month must be in 1..12")
            p["fiscal_year_start_month"] = v
        else:
            p["fiscal_year_start_month"] = 1


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------

@bp.route("/api/programs", methods=["POST"])
def create_program():
    _, role = auth_context()
    require_role(role, ["HRAdmin"])
    b = body()
    p = {"id": db.new_id(), "status": "DRAFT"}
    _apply_program_fields(p, b, partial=False)
    db.stamp(p)
    db.programs[p["id"]] = p
    return success(ser.program(p), 201)


@bp.route("/api/programs/<programId>", methods=["GET"])
def get_program(programId):
    _, role = auth_context()
    require_role(role, READ_ROLES)
    p = get_or_404(db.programs, programId, "Program")
    return success(ser.program(p))


@bp.route("/api/programs/<programId>", methods=["PATCH"])
def patch_program(programId):
    user_id, role = auth_context()
    require_role(role, ["HRAdmin"])
    p = get_or_404(db.programs, programId, "Program")
    b = body()
    # Schema stage: expected_program_version is non-optional (PRD 2.7).
    expected = req_int(b, "expected_program_version")
    # State stage: status transition validity (close guards included).
    new_status = b.get("status")
    if new_status is not None:
        if not isinstance(new_status, str) or new_status not in (
                "DRAFT", "ACTIVE", "SUSPENDED", "CLOSED"):
            raise_err(ERR_INVALID_REQUEST, "Invalid status value")
        if new_status == "CLOSED" and p["status"] != "CLOSED":
            if p["status"] != "ACTIVE":
                raise_err(ERR_INVALID_STATE_TRANSITION,
                          "Program can only be CLOSED from ACTIVE")
            open_noms = any(
                n["program_id"] == p["id"]
                and n["status"] in svc.NON_TERMINAL_NOMINATION_STATUSES
                for n in db.nominations.values())
            if open_noms:
                raise_err(ERR_INVALID_STATE_TRANSITION,
                          "Program has non-terminal nominations")
            open_orders = any(
                o["program_id"] == p["id"] and o["fulfillment_status"] in (
                    "PENDING_SUBMISSION", "SUBMITTED", "SHIPPED",
                    "RETURN_REQUESTED")
                for o in db.orders.values())
            if open_orders:
                raise_err(ERR_INVALID_STATE_TRANSITION,
                          "Program has open redemption orders")
        elif new_status != p["status"]:
            raise_err(ERR_INVALID_STATE_TRANSITION,
                      "Program status cannot be changed to %s via PATCH"
                      % new_status)
    # OCC stage.
    if expected != p["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_program_version %s does not match current version %s"
                  % (expected, p["version"]))
    # Apply config edits.
    _apply_program_fields(p, b, partial=True)
    if new_status == "CLOSED":
        p["status"] = "CLOSED"
    touch(p)
    return success(ser.program(p))


@bp.route("/api/programs/<programId>/activate", methods=["POST"])
def activate_program(programId):
    _, role = auth_context()
    require_role(role, ["HRAdmin"])
    p = get_or_404(db.programs, programId, "Program")
    if p["status"] not in ("DRAFT", "SUSPENDED"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Program can only be activated from DRAFT or SUSPENDED")
    if p["status"] == "DRAFT":
        has_mode = p["peer_nomination_enabled"] or p["manager_nomination_enabled"]
        if not p["anniversary_milestones"] and not has_mode:
            raise_err(ERR_INVALID_REQUEST,
                      "Program needs at least one milestone or nomination mode")
    p["status"] = "ACTIVE"
    touch(p)
    return success(ser.program(p))


@bp.route("/api/programs/<programId>/suspend", methods=["POST"])
def suspend_program(programId):
    _, role = auth_context()
    require_role(role, ["HRAdmin"])
    p = get_or_404(db.programs, programId, "Program")
    if p["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Program can only be suspended from ACTIVE")
    p["status"] = "SUSPENDED"
    touch(p)
    return success(ser.program(p))


def require_active_program(p):
    if p["status"] != "ACTIVE":
        raise_err(ERR_PROGRAM_NOT_ACTIVE, "Program is not ACTIVE")


@bp.route("/api/programs/<programId>/analytics/participation", methods=["GET"])
def participation_analytics(programId):
    _, role = auth_context()
    require_role(role, READ_ROLES)
    p = get_or_404(db.programs, programId, "Program")
    raw = request.args.get("window_days")
    window_days = 90
    if raw is not None:
        try:
            window_days = int(raw)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "window_days must be an integer")
        if window_days <= 0:
            raise_err(ERR_INVALID_REQUEST, "window_days must be positive")
    from calc import compute_participation
    return success(compute_participation(p["id"], window_days))


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------

@bp.route("/api/departments", methods=["POST"])
def create_department():
    _, role = auth_context()
    require_role(role, ["HRAdmin"])
    b = body()
    d = {
        "id": db.new_id(),
        "name": req_str(b, "name"),
        "chargeback_account_code": req_str(b, "chargeback_account_code"),
    }
    db.stamp(d)
    db.departments[d["id"]] = d
    return success(ser.department(d), 201)


@bp.route("/api/departments/<departmentId>", methods=["GET"])
def get_department(departmentId):
    _, role = auth_context()
    require_role(role, READ_ROLES)
    d = get_or_404(db.departments, departmentId, "Department")
    return success(ser.department(d))


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------

def _check_manager_cycle(employee_id, manager_id):
    """manager_id must not equal own id nor create a reporting cycle."""
    if manager_id is None:
        return
    if manager_id == employee_id:
        raise_err(ERR_INVALID_REQUEST, "manager_id must not equal own id")
    seen = {employee_id}
    cur = manager_id
    while cur:
        if cur in seen:
            raise_err(ERR_INVALID_REQUEST,
                      "manager_id would create a reporting cycle")
        seen.add(cur)
        nxt = db.employees.get(cur)
        if nxt is None:
            break
        cur = nxt.get("manager_id")


@bp.route("/api/employees", methods=["POST"])
def create_employee():
    _, role = auth_context()
    require_role(role, ["HRAdmin"])
    b = body()
    employee_ref = req_str(b, "employee_ref")
    full_name = req_str(b, "full_name")
    department_id = b.get("department_id")
    manager_id = b.get("manager_id")
    hire_date = parse_iso_date(b.get("hire_date"), "hire_date")
    state_code = req_str(b, "state_code")
    # Existence of body-supplied foreign keys.
    if not isinstance(department_id, str) or department_id not in db.departments:
        raise_err(ERR_NOT_FOUND, "Department not found: %s" % department_id)
    if manager_id is not None:
        if not isinstance(manager_id, str):
            raise_err(ERR_INVALID_REQUEST, "manager_id must be a string")
        if manager_id not in db.employees:
            raise_err(ERR_NOT_FOUND, "Manager not found: %s" % manager_id)
    # Referential integrity: unique employee_ref, no reporting cycle.
    if any(e["employee_ref"] == employee_ref for e in db.employees.values()):
        raise_err(ERR_INVALID_REQUEST,
                  "employee_ref already registered: %s" % employee_ref)
    e = {
        "id": db.new_id(),
        "employee_ref": employee_ref,
        "full_name": full_name,
        "department_id": department_id,
        "manager_id": manager_id,
        "hire_date": hire_date,
        "state_code": state_code,
        "program_status": "ELIGIBLE",
        "recognition_tier": "BRONZE",
        "available_points": 0,
        "held_points": 0,
        "lifetime_granted_points": 0,
        "lifetime_redeemed_points": 0,
        "lifetime_expired_points": 0,
        "ytd_supplemental_wages_cents": 0,
        "ytd_de_minimis_cents": 0,
    }
    _check_manager_cycle(e["id"], manager_id)
    db.stamp(e)
    db.employees[e["id"]] = e
    return success(ser.employee(e), 201)


@bp.route("/api/employees/<employeeId>", methods=["GET"])
def get_employee(employeeId):
    _, role = auth_context()
    require_role(role, READ_ROLES)
    e = get_or_404(db.employees, employeeId, "Employee")
    return success(ser.employee(e))


@bp.route("/api/employees", methods=["GET"])
def list_employees():
    _, role = auth_context()
    require_role(role, READ_ROLES)
    rows = _sorted_rows(db.employees.values())
    dept = request.args.get("department_id")
    mgr = request.args.get("manager_id")
    status = request.args.get("program_status")
    if dept is not None:
        rows = [e for e in rows if e["department_id"] == dept]
    if mgr is not None:
        rows = [e for e in rows if e["manager_id"] == mgr]
    if status is not None:
        rows = [e for e in rows if e["program_status"] == status]
    return _paginate(rows, ser.employee)


@bp.route("/api/employees/<employeeId>/compensation-adjustments", methods=["POST"])
def compensation_adjustment(employeeId):
    _, role = auth_context()
    require_role(role, ["PayrollSpecialist"])
    e = get_or_404(db.employees, employeeId, "Employee")
    b = body()
    value = req_int(b, "ytd_supplemental_wages_cents")
    if value < 0:
        raise_err(ERR_INVALID_REQUEST,
                  "ytd_supplemental_wages_cents must be non-negative")
    e["ytd_supplemental_wages_cents"] = value
    touch(e)
    return success(ser.employee(e))


@bp.route("/api/employees/<employeeId>/reinstate", methods=["POST"])
def reinstate_employee(employeeId):
    _, role = auth_context()
    require_role(role, ["HRAdmin"])
    e = get_or_404(db.employees, employeeId, "Employee")
    if e["program_status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only a SUSPENDED employee can be reinstated")
    open_flags = any(
        f["employee_id"] == e["id"] and f["status"] in ("OPEN", "UNDER_REVIEW")
        for f in db.abuse_flags.values())
    if open_flags:
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Employee has open or under-review abuse flags")
    e["program_status"] = "ELIGIBLE"
    touch(e)
    return success(ser.employee(e))


@bp.route("/api/employees/<employeeId>/ledger-entries", methods=["GET"])
def list_ledger_entries(employeeId):
    _, role = auth_context()
    require_role(role, READ_ROLES)
    e = get_or_404(db.employees, employeeId, "Employee")
    rows = [x for x in db.ledger if x["employee_id"] == e["id"]]
    rows.sort(key=lambda x: x["created_at"])
    entry_type = request.args.get("entry_type")
    if entry_type is not None:
        rows = [x for x in rows if x["entry_type"] == entry_type]
    return _paginate(rows, ser.ledger_entry)


@bp.route("/api/employees/<employeeId>/points-adjustments", methods=["POST"])
def points_adjustment(employeeId):
    _, role = auth_context()
    require_role(role, ["HRAdmin"])
    e = get_or_404(db.employees, employeeId, "Employee")
    b = body()
    program_id = b.get("program_id")
    points = req_int(b, "points")
    reason = req_str(b, "reason")
    if points <= 0:
        raise_err(ERR_INVALID_REQUEST, "points must be > 0")
    if not isinstance(program_id, str) or program_id not in db.programs:
        raise_err(ERR_NOT_FOUND, "Program not found: %s" % program_id)
    # Budget selected exactly like a nomination grant (window contains today).
    budget = svc.select_budget(program_id, e["department_id"], now().date())
    if budget is None:
        raise_err(ERR_BUDGET_NOT_FOUND,
                  "No budget window contains the current date")
    if budget["reserved_points"] + budget["committed_points"] + points \
            > budget["allocated_points"]:
        raise_err(ERR_BUDGET_EXHAUSTED, "Budget capacity exceeded")
    award = svc.create_award(program_id, e, points, "ADJUSTMENT",
                             nomination_id=None)
    svc.post_ledger(e, "GRANT_ADJUSTMENT", points, "AWARD", award["id"],
                    "adjustment:%s:GRANT_ADJUSTMENT" % award["id"],
                    "HR adjustment grant: %s" % reason)
    svc.emp_grant(e, points)
    budget["committed_points"] += points
    svc.budget_mutated(budget)
    return success(ser.award(award), 201)


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

@bp.route("/api/budgets", methods=["POST"])
def create_budget():
    _, role = auth_context()
    require_role(role, ["FinanceAdmin"])
    b = body()
    program_id = b.get("program_id")
    department_id = b.get("department_id")
    start = parse_iso_date(b.get("period_start_date"), "period_start_date")
    end = parse_iso_date(b.get("period_end_date"), "period_end_date")
    allocated = req_int(b, "allocated_points")
    if end <= start:
        raise_err(ERR_INVALID_REQUEST,
                  "period_end_date must be after period_start_date")
    if allocated <= 0:
        raise_err(ERR_INVALID_REQUEST, "allocated_points must be > 0")
    if not isinstance(program_id, str) or program_id not in db.programs:
        raise_err(ERR_NOT_FOUND, "Program not found: %s" % program_id)
    if not isinstance(department_id, str) or department_id not in db.departments:
        raise_err(ERR_NOT_FOUND, "Department not found: %s" % department_id)
    program = db.programs[program_id]
    require_active_program(program)
    # Temporal: half-open overlap check; pure adjacency is allowed.
    for other in db.budgets.values():
        if other["program_id"] == program_id \
                and other["department_id"] == department_id:
            if start < other["period_end_date"] and other["period_start_date"] < end:
                raise_err(ERR_BUDGET_PERIOD_OVERLAP,
                          "Budget window overlaps an existing window")
    budget = {
        "id": db.new_id(),
        "program_id": program_id,
        "department_id": department_id,
        "period_start_date": start,
        "period_end_date": end,
        "allocated_points": allocated,
        "reserved_points": 0,
        "committed_points": 0,
        "posture": "OPEN",
    }
    db.stamp(budget)
    svc.recompute_posture(budget)
    db.budgets[budget["id"]] = budget
    return success(ser.budget(budget), 201)


@bp.route("/api/budgets/<budgetId>", methods=["GET"])
def get_budget(budgetId):
    _, role = auth_context()
    require_role(role, READ_ROLES)
    b = get_or_404(db.budgets, budgetId, "PointBudget")
    return success(ser.budget(b))


@bp.route("/api/budgets", methods=["GET"])
def list_budgets():
    _, role = auth_context()
    require_role(role, READ_ROLES)
    rows = _sorted_rows(db.budgets.values())
    pid = request.args.get("program_id")
    did = request.args.get("department_id")
    posture = request.args.get("posture")
    if pid is not None:
        rows = [b for b in rows if b["program_id"] == pid]
    if did is not None:
        rows = [b for b in rows if b["department_id"] == did]
    if posture is not None:
        rows = [b for b in rows if b["posture"] == posture]
    return _paginate(rows, ser.budget)


@bp.route("/api/budgets/<budgetId>/adjustments", methods=["POST"])
def budget_adjustment(budgetId):
    _, role = auth_context()
    require_role(role, ["FinanceAdmin"])
    budget = get_or_404(db.budgets, budgetId, "PointBudget")
    b = body()
    delta = req_int(b, "delta_allocated_points")
    req_str(b, "reason")
    expected = req_int(b, "expected_budget_version")
    # OCC (stage 6) precedes the CLOSED-budget fiscal check (stage 18).
    if expected != budget["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_budget_version %s does not match current version %s"
                  % (expected, budget["version"]))
    if budget["posture"] == "CLOSED":
        raise_err(ERR_BUDGET_CLOSED, "Budget is CLOSED")
    result = budget["allocated_points"] + delta
    if result <= 0 or result < budget["reserved_points"] + budget["committed_points"]:
        raise_err(ERR_INVALID_REQUEST,
                  "Adjusted allocation must stay > 0 and >= reserved+committed")
    budget["allocated_points"] = result
    svc.budget_mutated(budget)
    return success(ser.budget(budget))
