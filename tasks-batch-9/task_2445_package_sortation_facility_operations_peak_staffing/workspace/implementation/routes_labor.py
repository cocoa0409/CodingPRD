"""Shift plans, the hiring pipeline and line staffing (PRD §3.4 - §3.7, §3.9)."""

from flask import Blueprint, g, request

import services as sv
from core import (
    FACILITY_ADMIN,
    LABOR_PLANNER,
    OPS_MANAGER,
    SORT_SUPERVISOR,
    WORKER,
    ApiError,
    authorize,
    body_dict,
    clock_dt,
    clock_raw,
    db,
    filter_bool,
    filter_enum,
    get_center,
    get_facility,
    get_labor,
    get_shift_plan,
    new_entity,
    opt_int,
    pagination,
    paginate,
    parse_date_only,
    q,
    req_enum,
    req_id,
    req_int,
    req_str,
    respond_entity,
    respond_list,
    touch,
)

bp = Blueprint("labor", __name__)

PLAN_STATES = ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "AT_RISK", "CLOSED")
WORKER_STATES = ("APPLIED", "ONBOARDING", "CLEARED", "CERTIFIED", "SEPARATED")
HIRE_CLASSES = ("CORE", "SEASONAL", "FLEX")
ASSIGNMENT_STATES = ("ASSIGNED", "CHECKED_IN", "COMPLETED", "NO_SHOW")
LINE_ROLES = ("UNLOADER", "PRIMARY_SORTER", "SECONDARY_SORTER", "LOADER", "JAM_TECH")
EVENT_TYPES = (
    "ONBOARDING_STARTED",
    "BACKGROUND_CLEARED",
    "TRAINING_SESSION_COMPLETED",
    "TRAINING_SESSION_MISSED",
    "REST_DAY_RECORDED",
    "CERTIFIED",
    "SEPARATED",
)

PLAN_READ_ROLES = [FACILITY_ADMIN, LABOR_PLANNER, OPS_MANAGER, SORT_SUPERVISOR]


# --------------------------------------------------------------------------
# ShiftPlan
# --------------------------------------------------------------------------


@bp.post("/sortation/sort-centers/<center_id>/shift-plans")
def create_plan(center_id):
    authorize([LABOR_PLANNER])
    body = body_dict()
    shift_date = req_str(body, "shift_date")
    if parse_date_only(shift_date) is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'shift_date' must be a YYYY-MM-DD date.")
    start_raw = req_str(body, "shift_window_start")
    end_raw = req_str(body, "shift_window_end")
    forecast_volume = req_int(body, "forecast_volume", min_value=1)
    core = req_int(body, "planned_core_headcount", min_value=0)
    seasonal = req_int(body, "planned_seasonal_headcount", min_value=0)
    budget = req_int(body, "labor_budget_cents", min_value=0)

    center = get_center(center_id)

    start_dt = sv.parse_window(start_raw, "shift_window_start")
    end_dt = sv.parse_window(end_raw, "shift_window_end")
    sv.require_ordered(start_dt, end_dt)

    for existing in sv.plans_of(center["id"]):
        if existing["shift_date"] == shift_date and existing["status"] != "REJECTED":
            raise ApiError(
                "ERR_DUPLICATE_FACILITY_RESOURCE",
                "A plan for this shift date already exists at this center.",
            )

    row = new_entity(
        "ShiftPlan",
        {
            "sort_center_id": center["id"],
            "shift_date": shift_date,
            "shift_window_start": start_raw,
            "shift_window_end": end_raw,
            "shift_hours": sv.calc_shift_hours(start_dt, end_dt),
            "forecast_volume": forecast_volume,
            "planned_core_headcount": core,
            "planned_seasonal_headcount": seasonal,
            "labor_budget_cents": budget,
            "required_headcount": 0,
            "flex_draw_count": 0,
            "planned_labor_cents": 0,
            "committed_headcount": 0,
            "staffing_gap": 0,
            "unfilled_gap": 0,
            "sorted_package_count": 0,
            "missort_package_count": 0,
            "actual_labor_cents": 0,
            "provisional_cost_per_package_cents": None,
            "final_cost_per_package_cents": None,
            "submitted_by_user_id": None,
            "approved_by_user_id": None,
            "rejection_reason": None,
            "status": "DRAFT",
            "_shift_window_start": start_dt,
            "_shift_window_end": end_dt,
        },
    )
    db.shift_plans[row["id"]] = row
    return respond_entity(row, 201)


@bp.get("/sortation/sort-centers/<center_id>/shift-plans")
def list_plans(center_id):
    authorize(PLAN_READ_ROLES)
    limit, offset = pagination()
    status = filter_enum("status", PLAN_STATES)
    shift_date = request.args.get("shift_date") or None
    center = get_center(center_id)
    rows = sv.plans_of(center["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if shift_date is not None:
        rows = [r for r in rows if r["shift_date"] == shift_date]
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


@bp.get("/sortation/shift-plans/<plan_id>")
def read_plan(plan_id):
    authorize(PLAN_READ_ROLES + [WORKER])
    return respond_entity(get_shift_plan(plan_id))


@bp.post("/sortation/shift-plans/<plan_id>/submit")
def submit_plan(plan_id):
    authorize([LABOR_PLANNER])
    plan = get_shift_plan(plan_id)
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_SHIFT_PLAN_STATE")
    center = get_center(plan["sort_center_id"])

    plan["shift_hours"] = sv.calc_shift_hours(
        plan["_shift_window_start"], plan["_shift_window_end"]
    )
    plan["required_headcount"] = sv.calc_required_headcount(plan, center)
    plan["submitted_by_user_id"] = g.user_id
    plan["status"] = "SUBMITTED"
    touch(plan)
    return respond_entity(plan)


@bp.post("/sortation/shift-plans/<plan_id>/approve")
def approve_plan(plan_id):
    authorize([OPS_MANAGER])
    body = body_dict()
    expected_version = req_int(body, "expected_center_version")
    plan = get_shift_plan(plan_id)
    center = get_center(plan["sort_center_id"])

    if plan["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_SHIFT_PLAN_STATE")
    if expected_version != center["version"]:
        raise ApiError("ERR_STALE_CENTER_VERSION")
    if plan["submitted_by_user_id"] is not None and g.user_id == plan["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    sv.require_not_frozen(center)

    core = plan["planned_core_headcount"]
    seasonal = plan["planned_seasonal_headcount"]
    needed_flex = plan["required_headcount"] - core - seasonal
    if needed_flex < 0:
        needed_flex = 0

    lines = sv.line_count(center["id"])
    if core + seasonal + needed_flex > sv.MAX_LINE_HEADCOUNT * lines:
        raise ApiError("ERR_LINE_HEADCOUNT_EXCEEDED")
    if center["flex_pool_available"] < needed_flex:
        raise ApiError("ERR_FLEX_POOL_EXHAUSTED")

    planned_cents = sv.calc_planned_labor_cents(plan, needed_flex)
    if planned_cents > plan["labor_budget_cents"]:
        raise ApiError("ERR_LABOR_BUDGET_EXCEEDED")

    plan["status"] = "APPROVED"
    plan["approved_by_user_id"] = g.user_id
    plan["flex_draw_count"] = needed_flex
    plan["planned_labor_cents"] = planned_cents
    plan["provisional_cost_per_package_cents"] = sv.calc_provisional_cost_per_package(plan)
    center["flex_pool_available"] = center["flex_pool_available"] - needed_flex
    center["flex_pool_reserved"] = center["flex_pool_reserved"] + needed_flex
    sv.recompute_plan_staffing(plan)
    touch(plan)
    touch(center)
    return respond_entity(plan)


@bp.post("/sortation/shift-plans/<plan_id>/reject")
def reject_plan(plan_id):
    authorize([OPS_MANAGER])
    body = body_dict()
    reason = req_str(body, "rejection_reason")
    plan = get_shift_plan(plan_id)
    if plan["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_SHIFT_PLAN_STATE")
    if plan["submitted_by_user_id"] is not None and g.user_id == plan["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    plan["status"] = "REJECTED"
    plan["rejection_reason"] = reason
    touch(plan)
    return respond_entity(plan)


@bp.post("/sortation/shift-plans/<plan_id>/revise")
def revise_plan(plan_id):
    authorize([LABOR_PLANNER])
    body = body_dict()
    forecast_volume = opt_int(body, "forecast_volume", default=None, min_value=1)
    core = opt_int(body, "planned_core_headcount", default=None, min_value=0)
    seasonal = opt_int(body, "planned_seasonal_headcount", default=None, min_value=0)
    budget = opt_int(body, "labor_budget_cents", default=None, min_value=0)
    plan = get_shift_plan(plan_id)
    if plan["status"] != "REJECTED":
        raise ApiError("ERR_INVALID_SHIFT_PLAN_STATE")

    if forecast_volume is not None:
        plan["forecast_volume"] = forecast_volume
    if core is not None:
        plan["planned_core_headcount"] = core
    if seasonal is not None:
        plan["planned_seasonal_headcount"] = seasonal
    if budget is not None:
        plan["labor_budget_cents"] = budget
    plan["status"] = "DRAFT"
    plan["rejection_reason"] = None
    plan["submitted_by_user_id"] = None
    plan["required_headcount"] = 0
    touch(plan)
    return respond_entity(plan)


@bp.post("/sortation/shift-plans/<plan_id>/close")
def close_plan(plan_id):
    authorize([OPS_MANAGER])
    body = body_dict()
    expected_version = req_int(body, "expected_center_version")
    plan = get_shift_plan(plan_id)
    center = get_center(plan["sort_center_id"])

    if plan["status"] not in ("APPROVED", "AT_RISK"):
        raise ApiError("ERR_INVALID_SHIFT_PLAN_STATE")
    if expected_version != center["version"]:
        raise ApiError("ERR_STALE_CENTER_VERSION")

    plan["actual_labor_cents"] = sv.calc_actual_labor_cents(plan)
    plan["final_cost_per_package_cents"] = sv.calc_final_cost_per_package(plan)
    plan["status"] = "CLOSED"
    touch(plan)

    draw = plan["flex_draw_count"]
    center["flex_pool_available"] = center["flex_pool_available"] + draw
    center["flex_pool_reserved"] = center["flex_pool_reserved"] - draw
    touch(center)

    sv.end_chute_assignments_for_close(plan)
    sv.recompute_center_posture(center)
    return respond_entity(plan)


# --------------------------------------------------------------------------
# Worker
# --------------------------------------------------------------------------


@bp.post("/sortation/sort-centers/<center_id>/workers")
def create_worker(center_id):
    authorize([LABOR_PLANNER])
    body = body_dict()
    full_name = req_str(body, "full_name")
    hire_class = req_enum(body, "hire_class", HIRE_CLASSES)
    hire_date_raw = req_str(body, "hire_date")
    hire_date = parse_date_only(hire_date_raw)
    if hire_date is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'hire_date' must be a YYYY-MM-DD date.")
    center = get_center(center_id)

    row = new_entity(
        "Worker",
        {
            "sort_center_id": center["id"],
            "full_name": full_name,
            "hire_class": hire_class,
            "hire_date": hire_date_raw,
            "status": "APPLIED",
            "training_sessions_completed": 0,
            "training_sessions_missed": 0,
            "no_show_count": 0,
            "completed_assignment_count": 0,
            "consecutive_completed_shifts": 0,
            "tenure_days": 0,
            "attrition_risk_score": q(0, 4),
            "attrition_risk_basis": "COHORT_BASELINE",
            "attrition_flagged": False,
            "_hire_date": hire_date,
        },
    )
    sv.recompute_attrition(row)
    db.workers[row["id"]] = row
    return respond_entity(row, 201)


@bp.get("/sortation/sort-centers/<center_id>/workers")
def list_workers(center_id):
    authorize(PLAN_READ_ROLES)
    limit, offset = pagination()
    status = filter_enum("status", WORKER_STATES)
    hire_class = filter_enum("hire_class", HIRE_CLASSES)
    flagged = filter_bool("attrition_flagged")
    center = get_center(center_id)
    rows = [w for w in db.workers.values() if w["sort_center_id"] == center["id"]]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if hire_class is not None:
        rows = [r for r in rows if r["hire_class"] == hire_class]
    if flagged is not None:
        rows = [r for r in rows if bool(r["attrition_flagged"]) == flagged]
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


@bp.get("/sortation/workers/<worker_id>")
def read_worker(worker_id):
    authorize(PLAN_READ_ROLES + [WORKER])
    return respond_entity(get_labor(db.workers, worker_id))


@bp.post("/sortation/workers/<worker_id>/onboarding-events")
def onboarding_event(worker_id):
    authorize([LABOR_PLANNER])
    body = body_dict()
    event_type = req_enum(body, "event_type", EVENT_TYPES)
    worker = get_labor(db.workers, worker_id)
    status = worker["status"]

    if event_type == "ONBOARDING_STARTED":
        if status != "APPLIED":
            raise ApiError("ERR_WORKER_NOT_CLEARED")
        worker["status"] = "ONBOARDING"
    elif event_type == "BACKGROUND_CLEARED":
        if status != "ONBOARDING":
            raise ApiError("ERR_WORKER_NOT_CLEARED")
        worker["status"] = "CLEARED"
    elif event_type in (
        "TRAINING_SESSION_COMPLETED",
        "TRAINING_SESSION_MISSED",
        "REST_DAY_RECORDED",
    ):
        if status not in ("CLEARED", "CERTIFIED"):
            raise ApiError("ERR_WORKER_NOT_CLEARED")
        if event_type == "TRAINING_SESSION_COMPLETED":
            worker["training_sessions_completed"] = worker["training_sessions_completed"] + 1
        elif event_type == "TRAINING_SESSION_MISSED":
            worker["training_sessions_missed"] = worker["training_sessions_missed"] + 1
        else:
            worker["consecutive_completed_shifts"] = 0
    elif event_type == "CERTIFIED":
        if status != "CLEARED":
            raise ApiError("ERR_WORKER_NOT_CLEARED")
        if worker["training_sessions_completed"] < sv.REQUIRED_TRAINING_SESSIONS:
            raise ApiError("ERR_WORKER_NOT_CLEARED")
        worker["status"] = "CERTIFIED"
    else:  # SEPARATED
        if status not in ("CLEARED", "CERTIFIED"):
            raise ApiError("ERR_WORKER_NOT_CLEARED")
        worker["status"] = "SEPARATED"

    sv.recompute_attrition(worker)
    touch(worker)

    if event_type == "SEPARATED":
        affected = [
            a for a in sv.assignments_of_worker(worker["id"]) if a["status"] == "ASSIGNED"
        ]
        affected.sort(key=lambda a: a["_seq"])
        for assignment in affected:
            sv.run_no_show_cascade(assignment)

    return respond_entity(worker)


# --------------------------------------------------------------------------
# StaffAssignment
# --------------------------------------------------------------------------


@bp.post("/sortation/staff-assignments")
def create_staff_assignment():
    authorize([LABOR_PLANNER, SORT_SUPERVISOR])
    body = body_dict()
    plan_id = req_id(body, "shift_plan_id")
    worker_id = req_id(body, "worker_id")
    line_chute_id = req_id(body, "line_chute_id")
    role_on_line = req_enum(body, "role_on_line", LINE_ROLES)

    chute = get_facility(db.sort_chutes, line_chute_id)
    plan = get_shift_plan(plan_id)
    worker = get_labor(db.workers, worker_id)

    if plan["status"] not in ("APPROVED", "AT_RISK"):
        raise ApiError("ERR_INVALID_SHIFT_PLAN_STATE")
    center = get_center(plan["sort_center_id"])
    sv.require_not_frozen(center)

    on_line = len(
        [
            a
            for a in db.staff_assignments.values()
            if a["line_chute_id"] == chute["id"] and a["status"] != "NO_SHOW"
        ]
    )
    if on_line + 1 > sv.MAX_LINE_HEADCOUNT:
        raise ApiError("ERR_LINE_HEADCOUNT_EXCEEDED")

    if worker["consecutive_completed_shifts"] >= sv.MAX_CONSECUTIVE_SHIFTS:
        raise ApiError("ERR_ERGONOMIC_ROTATION_REQUIRED")
    for report in db.injury_reports.values():
        if (
            report["worker_id"] == worker["id"]
            and report["status"] == "OPEN"
            and report["severity"] in ("RECORDABLE", "SERIOUS")
        ):
            raise ApiError("ERR_ERGONOMIC_ROTATION_REQUIRED")

    if worker["status"] not in ("CLEARED", "CERTIFIED"):
        raise ApiError("ERR_WORKER_NOT_CLEARED")

    if worker["sort_center_id"] != plan["sort_center_id"]:
        raise ApiError(
            "ERR_WORKER_CENTER_MISMATCH", "The worker belongs to a different sort center."
        )
    if chute["sort_center_id"] != plan["sort_center_id"]:
        raise ApiError(
            "ERR_WORKER_CENTER_MISMATCH", "The line belongs to a different sort center."
        )

    row = new_entity(
        "StaffAssignment",
        {
            "shift_plan_id": plan["id"],
            "worker_id": worker["id"],
            "line_chute_id": chute["id"],
            "role_on_line": role_on_line,
            "status": "ASSIGNED",
            "checked_in_at": None,
            "checked_out_at": None,
            "worked_hours": q(0, 2),
            "_checked_in_dt": None,
            "_checked_out_dt": None,
        },
    )
    db.staff_assignments[row["id"]] = row

    if sv.recompute_plan_staffing(plan):
        touch(plan)
    return respond_entity(row, 201)


@bp.get("/sortation/staff-assignments")
def list_staff_assignments():
    authorize(PLAN_READ_ROLES + [WORKER])
    limit, offset = pagination()
    status = filter_enum("status", ASSIGNMENT_STATES)
    role_on_line = filter_enum("role_on_line", LINE_ROLES)
    rows = list(db.staff_assignments.values())
    for field in ("shift_plan_id", "worker_id", "line_chute_id"):
        value = request.args.get(field) or None
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if role_on_line is not None:
        rows = [r for r in rows if r["role_on_line"] == role_on_line]
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


@bp.get("/sortation/staff-assignments/<assignment_id>")
def read_staff_assignment(assignment_id):
    authorize(PLAN_READ_ROLES + [WORKER])
    return respond_entity(get_labor(db.staff_assignments, assignment_id))


@bp.post("/sortation/staff-assignments/<assignment_id>/check-in")
def check_in(assignment_id):
    authorize([WORKER])
    assignment = get_labor(db.staff_assignments, assignment_id)
    if assignment["worker_id"] != g.user_id:
        raise ApiError("ERR_NOT_ASSIGNMENT_OWNER")
    plan = db.shift_plans.get(assignment["shift_plan_id"])
    if plan is None or plan["status"] not in ("APPROVED", "AT_RISK"):
        raise ApiError("ERR_INVALID_SHIFT_PLAN_STATE")
    if assignment["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE")
    center = get_center(plan["sort_center_id"])
    sv.require_not_frozen(center)
    worker = db.workers.get(assignment["worker_id"])
    if worker is None or worker["status"] != "CERTIFIED":
        raise ApiError("ERR_WORKER_NOT_CLEARED")

    assignment["status"] = "CHECKED_IN"
    assignment["checked_in_at"] = clock_raw()
    assignment["_checked_in_dt"] = clock_dt()
    touch(assignment)
    return respond_entity(assignment)


@bp.post("/sortation/staff-assignments/<assignment_id>/check-out")
def check_out(assignment_id):
    authorize([WORKER])
    assignment = get_labor(db.staff_assignments, assignment_id)
    if assignment["worker_id"] != g.user_id:
        raise ApiError("ERR_NOT_ASSIGNMENT_OWNER")
    if assignment["status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE")

    out_dt = clock_dt()
    in_dt = assignment["_checked_in_dt"]
    assignment["status"] = "COMPLETED"
    assignment["checked_out_at"] = clock_raw()
    assignment["_checked_out_dt"] = out_dt
    if in_dt is not None:
        assignment["worked_hours"] = sv.calc_shift_hours(in_dt, out_dt)
    touch(assignment)

    worker = db.workers.get(assignment["worker_id"])
    if worker is not None:
        worker["completed_assignment_count"] = worker["completed_assignment_count"] + 1
        worker["consecutive_completed_shifts"] = worker["consecutive_completed_shifts"] + 1
        sv.recompute_attrition(worker)
        touch(worker)
    return respond_entity(assignment)


@bp.post("/sortation/staff-assignments/<assignment_id>/no-show")
def no_show(assignment_id):
    authorize([LABOR_PLANNER, SORT_SUPERVISOR])
    assignment = get_labor(db.staff_assignments, assignment_id)
    if assignment["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE")
    sv.run_no_show_cascade(assignment)
    return respond_entity(assignment)
