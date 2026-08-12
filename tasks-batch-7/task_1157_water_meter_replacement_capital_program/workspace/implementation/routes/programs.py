"""Program endpoints (PRD 3.1) plus the completion report."""
import math
from datetime import timedelta
from fractions import Fraction

import db
from db import base_resource, clock_now, touch
from errors import raise_err
from middleware import ALL_ROLES, require_roles
from response import ok_list, ok_object
from services.core import (
    get_or_404,
    list_page,
    program_derived,
    ser_program,
    work_orders_of_program,
)
from flask import Blueprint, request
from validate import body, opt_int, req_int, req_str

bp = Blueprint("programs", __name__)

STAGE_WEIGHTS = {
    "CREATED": Fraction(5, 100),
    "NOTIFIED": Fraction(15, 100),
    "SCHEDULED": Fraction(30, 100),
    "ACCESS_FAILED": Fraction(25, 100),
    "SWAPPED": Fraction(60, 100),
    "RECONCILED": Fraction(75, 100),
    "AMI_VERIFIED": Fraction(85, 100),
    "QA_REVIEW": Fraction(90, 100),
    "QA_FAILED": Fraction(55, 100),
}


@bp.post("/api/programs")
@require_roles("ProgramManager")
def create_program():
    b = body()
    p = base_resource()
    p.update({
        "name": req_str(b, "name"),
        "fiscal_year": req_str(b, "fiscal_year"),
        "budget_total_cents": req_int(b, "budget_total_cents", min=1),
        "target_meter_count": req_int(b, "target_meter_count", min=1),
        "rate_per_ccf_cents": req_int(b, "rate_per_ccf_cents", min=0),
        "default_unit_allowance_cents": req_int(b, "default_unit_allowance_cents", min=0),
        "notice_days": opt_int(b, "notice_days", default=3, min=0),
        "status": "PLANNING",
    })
    db.programs[p["id"]] = p
    return ok_object(ser_program(p), 201)


@bp.get("/api/programs")
@require_roles(*ALL_ROLES)
def list_programs():
    filters = {}
    if request.args.get("status") is not None:
        filters["status"] = request.args["status"]
    return list_page(db.programs.values(), filters, ser_program)


@bp.get("/api/programs/<programId>")
@require_roles(*ALL_ROLES)
def get_program(programId):
    return ok_object(ser_program(get_or_404(db.programs, programId, "Program")))


@bp.post("/api/programs/<programId>/activate")
@require_roles("ProgramManager")
def activate_program(programId):
    p = get_or_404(db.programs, programId, "Program")
    if p["status"] != "PLANNING":
        raise_err("ERR_INVALID_STATE", "Program is not in PLANNING")
    p["status"] = "ACTIVE"
    touch(p)
    return ok_object(ser_program(p))


@bp.post("/api/programs/<programId>/begin-closing")
@require_roles("ProgramManager")
def begin_closing_program(programId):
    p = get_or_404(db.programs, programId, "Program")
    if p["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "Program is not in ACTIVE")
    for w in db.waves.values():
        if w["program_id"] == p["id"] and w["status"] not in ("COMPLETE", "CANCELLED"):
            raise_err("ERR_INVALID_STATE",
                      "Every wave must be COMPLETE or CANCELLED before closing")
    p["status"] = "CLOSING"
    touch(p)
    return ok_object(ser_program(p))


@bp.post("/api/programs/<programId>/close")
@require_roles("ProgramManager")
def close_program(programId):
    p = get_or_404(db.programs, programId, "Program")
    if p["status"] != "CLOSING":
        raise_err("ERR_INVALID_STATE", "Program is not in CLOSING")
    for inv in db.invoices.values():
        if inv["program_id"] == p["id"] and inv["status"] != "APPROVED":
            raise_err("ERR_INVALID_STATE",
                      "Every invoice must be APPROVED before program closure")
    p["status"] = "CLOSED"
    touch(p)
    return ok_object(ser_program(p))


@bp.get("/api/programs/<programId>/completion-report")
@require_roles("ProgramManager")
def completion_report(programId):
    p = get_or_404(db.programs, programId, "Program")
    committed, spent, available, posture, completed = program_derived(p)
    target = p["target_meter_count"]
    completion_pct = _completion_pct(completed, target)

    now = clock_now()
    days_elapsed = max(1, math.floor((now - p["created_at"]).total_seconds() / 86400))

    # RUN_RATE variant (PRD 3.1): rate floored at 1/10000 meter per day.
    daily_rate = max(Fraction(completed, days_elapsed), Fraction(1, 10000))
    run_rate_days = math.ceil(Fraction(target - completed) / daily_rate)
    forecast_run_rate_date = (now.date() + timedelta(days=run_rate_days)).isoformat()

    # STAGE_WEIGHTED variant: fractional credit per open work order.
    equivalent_done = Fraction(completed)
    for wo in work_orders_of_program(p["id"]):
        w = STAGE_WEIGHTS.get(wo["lifecycle_status"])
        if w is not None:
            equivalent_done += w
    weekly_capacity = sum(
        c["crew_capacity_per_window"] * 9
        for c in db.contractors.values()
        if c["program_id"] == p["id"] and c["status"] == "ACTIVE"
    )
    remaining_weeks = Fraction(target) - equivalent_done
    remaining_weeks /= max(weekly_capacity, 1)
    stage_days = math.ceil(remaining_weeks * 7)
    forecast_stage_weighted_date = (now.date() + timedelta(days=stage_days)).isoformat()

    return ok_object({
        "completed_meter_count": completed,
        "target_meter_count": target,
        "completion_pct": completion_pct,
        "budget_total_cents": p["budget_total_cents"],
        "budget_committed_cents": committed,
        "budget_spent_cents": spent,
        "budget_available_cents": available,
        "budget_posture": posture,
        "forecast_run_rate_date": forecast_run_rate_date,
        "forecast_stage_weighted_date": forecast_stage_weighted_date,
    })


def _completion_pct(completed, target):
    from decimal import Decimal, ROUND_HALF_UP

    value = Decimal(completed) / Decimal(target) * 100
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
