"""Operator endpoints: registration, lifecycle, and reverse-lookup collections."""
from flask import request, Blueprint

from db import db, mint, touch, ser
from errors import invalid_state, validation
from helpers import (
    body_json,
    req_str,
    req_date,
    opt_int,
    get_operator_or_404,
    recompute_seniority,
    paginated,
)
from middleware import authenticate, require_roles, ALL_ROLES, READ_SO_OP_UR
from response import ok_obj

bp = Blueprint("operators", __name__)

SO = ["SchedulingOfficer"]


@bp.post("/api/operators")
def create_operator():
    auth = authenticate()
    require_roles(auth, SO)
    body = body_json()
    employee_number = req_str(body, "employee_number")
    full_name = req_str(body, "full_name")
    hire_date = req_date(body, "hire_date")
    balance = opt_int(body, "vacation_hours_balance", 0)
    for o in db.operators.values():
        if o["employee_number"] == employee_number:
            raise validation("employee_number must be unique across the roster")
    op = mint()
    op.update(
        {
            "employee_number": employee_number,
            "full_name": full_name,
            "hire_date": hire_date,
            "seniority_rank": 0,
            "status": "ACTIVE",
            "board_position": None,
            "weekly_ot_minutes_accum": 0,
            "vacation_hours_balance": balance,
        }
    )
    db.operators[op["id"]] = op
    recompute_seniority()
    return ok_obj(ser(op), 201)


@bp.get("/api/operators")
def list_operators():
    auth = authenticate()
    require_roles(auth, ALL_ROLES)
    items = list(db.operators.values())
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return paginated(items)


@bp.get("/api/operators/<oid>")
def get_operator(oid):
    auth = authenticate()
    require_roles(auth, ALL_ROLES)
    return ok_obj(ser(get_operator_or_404(oid)))


@bp.post("/api/operators/<oid>/suspend")
def suspend_operator(oid):
    auth = authenticate()
    require_roles(auth, SO)
    op = get_operator_or_404(oid)
    if op["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE operator may be suspended")
    op["status"] = "SUSPENDED"
    touch(op)
    # Cascade: withdraw the operator's SUBMITTED bids in OPEN or PICKING periods
    for b in db.bid_entries.values():
        if b["operator_id"] == oid and b["status"] == "SUBMITTED":
            period = db.sign_up_periods.get(b["sign_up_period_id"])
            if period is not None and period["status"] in ("OPEN", "PICKING"):
                b["status"] = "WITHDRAWN"
                touch(b)
    recompute_seniority()
    return ok_obj(ser(op))


@bp.post("/api/operators/<oid>/reinstate")
def reinstate_operator(oid):
    auth = authenticate()
    require_roles(auth, SO)
    op = get_operator_or_404(oid)
    if op["status"] != "SUSPENDED":
        raise invalid_state("Only a SUSPENDED operator may be reinstated")
    op["status"] = "ACTIVE"
    touch(op)
    recompute_seniority()
    return ok_obj(ser(op))


@bp.post("/api/operators/<oid>/retire")
def retire_operator(oid):
    auth = authenticate()
    require_roles(auth, SO)
    op = get_operator_or_404(oid)
    if op["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE operator may be retired")
    if any(
        a["operator_id"] == oid and a["status"] == "SCHEDULED"
        for a in db.daily_assignments.values()
    ):
        raise invalid_state("Operator holds SCHEDULED assignments and cannot be retired")
    op["status"] = "RETIRED"
    touch(op)
    recompute_seniority()
    return ok_obj(ser(op))


@bp.post("/api/operators/<oid>/promote")
def promote_operator(oid):
    auth = authenticate()
    require_roles(auth, SO)
    op = get_operator_or_404(oid)
    if op["status"] != "EXTRA_BOARD":
        raise invalid_state("Only an EXTRA_BOARD operator may be promoted")
    has_award = any(
        r["awarded_operator_id"] == oid and r["status"] == "AWARDED"
        for r in db.runs.values()
    )
    if not has_award:
        raise invalid_state("Operator holds no awarded run in the current sign-up")
    op["status"] = "ACTIVE"
    op["board_position"] = None
    touch(op)
    return ok_obj(ser(op))


# ---------------------------------------------------------------------------
# Reverse-lookup collections
# ---------------------------------------------------------------------------

@bp.get("/api/operators/<oid>/runs")
def operator_runs(oid):
    auth = authenticate()
    require_roles(auth, READ_SO_OP_UR)
    get_operator_or_404(oid)
    items = [r for r in db.runs.values() if r["awarded_operator_id"] == oid]
    return paginated(items)


@bp.get("/api/operators/<oid>/bid-entries")
def operator_bids(oid):
    auth = authenticate()
    require_roles(auth, READ_SO_OP_UR)
    get_operator_or_404(oid)
    items = [b for b in db.bid_entries.values() if b["operator_id"] == oid]
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return paginated(items)


@bp.get("/api/operators/<oid>/extra-board-slots")
def operator_board_slots(oid):
    auth = authenticate()
    require_roles(auth, READ_SO_OP_UR)
    get_operator_or_404(oid)
    items = [s for s in db.extra_board_slots.values() if s["operator_id"] == oid]
    return paginated(items)


@bp.get("/api/operators/<oid>/absence-cases")
def operator_absences(oid):
    auth = authenticate()
    require_roles(auth, READ_SO_OP_UR)
    get_operator_or_404(oid)
    items = [a for a in db.absence_cases.values() if a["operator_id"] == oid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return paginated(items)


@bp.get("/api/operators/<oid>/vacation-slots")
def operator_vacations(oid):
    auth = authenticate()
    require_roles(auth, READ_SO_OP_UR)
    get_operator_or_404(oid)
    items = [v for v in db.vacation_slots.values() if v["operator_id"] == oid]
    return paginated(items)


@bp.get("/api/operators/<oid>/grievance-cases")
def operator_grievances(oid):
    auth = authenticate()
    require_roles(auth, READ_SO_OP_UR)
    get_operator_or_404(oid)
    items = [
        g for g in db.grievance_cases.values() if g["filed_by_operator_id"] == oid
    ]
    status = request.args.get("status")
    if status is not None:
        items = [g for g in items if g["status"] == status]
    return paginated(items)
