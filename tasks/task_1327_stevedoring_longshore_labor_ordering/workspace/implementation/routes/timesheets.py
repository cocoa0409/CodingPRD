"""TimesheetEntry endpoints (PRD §3.8)."""
from flask import Blueprint, g, request

import errors
import services
from db import get, new_resource, pub, save, touch
from middleware import list_response, opt_bool, req_field, req_int, require_roles
from response import get_body, ok

bp = Blueprint("timesheets", __name__)

READ_ROLES = ("StevedoreAdmin", "StevedoreSuperintendent", "GangForeman", "PayrollClerk")
QUALIFYING_ASSIGNMENT_STATUSES = ("CHECKED_IN", "WORKING", "COMPLETED")
TIMESHEET_GRACE_MINUTES = 120


@bp.post("/api/timesheet-entries")
def create_timesheet():
    require_roles("GangForeman")
    body = get_body()
    # existence (3), left to right
    gang_order_id = req_field(body, "gang_order_id")
    gang = get("gang_orders", gang_order_id)
    if gang is None:
        raise errors.not_found("Gang order not found")
    worker_id = req_field(body, "worker_id")
    worker = get("workers", worker_id)
    if worker is None:
        raise errors.not_found("Worker not found")
    # schema (4)
    work_minutes = req_int(body, "work_minutes", min_value=0)
    meal_break_taken = opt_bool(body, "meal_break_taken", default=False)
    # referential (8): worker must hold a qualifying assignment on this gang order
    has_assignment = any(
        a["worker_id"] == worker_id and a["status"] in QUALIFYING_ASSIGNMENT_STATUSES
        for a in services.assignments_of_gang(gang["id"])
    )
    if not has_assignment:
        raise errors.worker_not_on_gang()
    # temporal (9): work_minutes must not exceed shift duration + 120
    shift = services.gang_shift(gang)
    shift_minutes = (shift["_end"] - shift["_start"]).total_seconds() / 60
    if work_minutes > shift_minutes + TIMESHEET_GRACE_MINUTES:
        raise errors.timesheet_exceeds_shift()
    rec = new_resource("timesheet_entries")
    rec.update({
        "gang_order_id": gang_order_id,
        "worker_id": worker_id,
        "work_minutes": work_minutes,
        "meal_break_taken": meal_break_taken,
        "status": "DRAFT",
        "rate_cents_snapshot": worker["base_hourly_rate_cents"],
        "straight_minutes": None,
        "ot_minutes": None,
        "dt_minutes": None,
        "meal_penalty_minutes": None,
        "gross_pay_cents": None,
        "bonus_cents": 0,
        "submitted_by_user_id": None,
    })
    save("timesheet_entries", rec)
    return ok(pub(rec), 201)


@bp.get("/api/timesheet-entries")
def list_timesheets():
    require_roles(*READ_ROLES)
    return list_response("timesheet_entries", {
        "gang_order_id": request.args.get("gang_order_id"),
        "worker_id": request.args.get("worker_id"),
        "status": request.args.get("status"),
    })


def _get_timesheet(tid):
    t = get("timesheet_entries", tid)
    if t is None:
        raise errors.not_found("Timesheet entry not found")
    return t


@bp.get("/api/timesheet-entries/<tid>")
def get_timesheet(tid):
    require_roles(*READ_ROLES)
    return ok(pub(_get_timesheet(tid)))


@bp.post("/api/timesheet-entries/<tid>/submit")
def submit_timesheet(tid):
    require_roles("GangForeman")
    t = _get_timesheet(tid)
    if t["status"] not in ("DRAFT", "REJECTED"):
        raise errors.invalid_state("Only a DRAFT or REJECTED timesheet can be submitted")
    t["status"] = "SUBMITTED"
    t["submitted_by_user_id"] = g.user_id
    touch(t)
    return ok(pub(t))


@bp.post("/api/timesheet-entries/<tid>/approve")
def approve_timesheet(tid):
    require_roles("PayrollClerk")
    t = _get_timesheet(tid)
    if t["status"] != "SUBMITTED":
        raise errors.invalid_state("Only a SUBMITTED timesheet can be approved")
    if g.user_id == t["submitted_by_user_id"]:
        raise errors.segregation("The approver must differ from the submitter")
    gang = get("gang_orders", t["gang_order_id"])
    straight, ot, dt, meal, gross = services.compute_payroll(t, gang)
    t["straight_minutes"] = straight
    t["ot_minutes"] = ot
    t["dt_minutes"] = dt
    t["meal_penalty_minutes"] = meal
    t["gross_pay_cents"] = gross
    t["bonus_cents"] = gang["bonus_per_worker_cents"]
    t["status"] = "APPROVED"
    touch(t)
    return ok(pub(t))


@bp.post("/api/timesheet-entries/<tid>/reject")
def reject_timesheet(tid):
    require_roles("PayrollClerk")
    t = _get_timesheet(tid)
    if t["status"] != "SUBMITTED":
        raise errors.invalid_state("Only a SUBMITTED timesheet can be rejected")
    t["status"] = "REJECTED"
    touch(t)
    return ok(pub(t))
