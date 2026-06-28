"""PayrollDeductionSchedule endpoints (PRD §3.5)."""
from flask import Blueprint, request

from db import db, parse_iso
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SCHEDULE_OVERLAP,
    ERR_DEDUCTION_LIMIT_EXCEEDED,
    ERR_SCHEDULE_WINDOW_CLOSED,
    ERR_CAMPAIGN_NOT_LIVE,
)
from middleware import get_user_context, require_role
from response import object_response, array_response
from services.common import (
    get_json_body,
    require_fields,
    require_string,
    require_positive_int,
    require_datetime,
    stamp_create,
    touch,
    serialize,
    find_or_404,
    paginate,
)
from services.calc import payroll_ceiling_cents

bp = Blueprint("payroll", __name__)


def _overlaps_half_open(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap: a_start < b_end and b_start < a_end."""
    return a_start < b_end and b_start < a_end


@bp.route("/payroll-schedules", methods=["POST"])
def create_schedule():
    uid, role = get_user_context()
    require_role(role, {"Employee", "GivingAdmin"})
    body = get_json_body()
    require_fields(body, ["program_id", "employee_id", "campaign_id", "per_period_amount_cents", "window_start", "window_end"])
    program_id = require_string(body, "program_id")
    employee_id = require_string(body, "employee_id")
    campaign_id = require_string(body, "campaign_id")
    per_period = require_positive_int(body, "per_period_amount_cents")
    window_start = require_datetime(body, "window_start")
    window_end = require_datetime(body, "window_end")

    find_or_404(db.programs, program_id)
    employee = find_or_404(db.employees, employee_id)
    find_or_404(db.campaigns, campaign_id)

    if role == "Employee" and uid != employee_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Employee may only create own schedule")

    ws = parse_iso(window_start)
    we = parse_iso(window_end)

    # Overlap (priority 11): vs existing ACTIVE/PAUSED for same employee+campaign.
    for s in db.payroll_schedules.values():
        if s["employee_id"] != employee_id or s["campaign_id"] != campaign_id:
            continue
        if s["status"] not in ("ACTIVE", "PAUSED"):
            continue
        if _overlaps_half_open(ws, we, parse_iso(s["window_start"]), parse_iso(s["window_end"])):
            raise err(ERR_SCHEDULE_OVERLAP, "Schedule window overlaps an existing ACTIVE/PAUSED schedule")

    # Deduction ceiling (priority 14): committed (ACTIVE/PAUSED) + new <= ceiling.
    ceiling = payroll_ceiling_cents(employee)
    committed = 0
    for s in db.payroll_schedules.values():
        if s["employee_id"] != employee_id:
            continue
        if s["status"] not in ("ACTIVE", "PAUSED"):
            continue
        committed += s["per_period_amount_cents"]
    if committed + per_period > ceiling:
        raise err(ERR_DEDUCTION_LIMIT_EXCEEDED,
                  "Committed + new per-period deduction exceeds 20% of monthly salary")

    rec = {
        "program_id": program_id,
        "employee_id": employee_id,
        "campaign_id": campaign_id,
        "per_period_amount_cents": per_period,
        "window_start": window_start,
        "window_end": window_end,
        "occurrences_generated": 0,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.payroll_schedules[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/payroll-schedules/<schedule_id>", methods=["GET"])
def get_schedule(schedule_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager", "Employee"})
    rec = find_or_404(db.payroll_schedules, schedule_id)
    return object_response(serialize(rec), 200)


@bp.route("/payroll-schedules", methods=["GET"])
def list_schedules():
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager", "Employee"})
    program_id = request.args.get("program_id")
    employee_id = request.args.get("employee_id")
    campaign_id = request.args.get("campaign_id")
    status = request.args.get("status")
    items = []
    for s in db.payroll_schedules.values():
        if program_id is not None and s["program_id"] != program_id:
            continue
        if employee_id is not None and s["employee_id"] != employee_id:
            continue
        if campaign_id is not None and s["campaign_id"] != campaign_id:
            continue
        if status is not None and s["status"] != status:
            continue
        items.append(s)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(s) for s in page], limit, offset, total, 200)


def _owner_transition(schedule_id, allowed_from, new_status):
    uid, role = get_user_context()
    require_role(role, {"Employee"})
    rec = find_or_404(db.payroll_schedules, schedule_id)
    if uid != rec["employee_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER, "Employee may only act on own schedule")
    if rec["status"] not in allowed_from:
        raise err(ERR_INVALID_STATE, f"Schedule must be in {allowed_from} for this transition")
    rec["status"] = new_status
    touch(rec)
    return object_response(serialize(rec), 200)


@bp.route("/payroll-schedules/<schedule_id>/pause", methods=["POST"])
def pause_schedule(schedule_id):
    return _owner_transition(schedule_id, {"ACTIVE"}, "PAUSED")


@bp.route("/payroll-schedules/<schedule_id>/resume", methods=["POST"])
def resume_schedule(schedule_id):
    return _owner_transition(schedule_id, {"PAUSED"}, "ACTIVE")


@bp.route("/payroll-schedules/<schedule_id>/cancel", methods=["POST"])
def cancel_schedule(schedule_id):
    return _owner_transition(schedule_id, {"ACTIVE", "PAUSED"}, "CANCELLED")


@bp.route("/payroll-schedules/<schedule_id>/run-cycle", methods=["POST"])
def run_cycle(schedule_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin"})
    rec = find_or_404(db.payroll_schedules, schedule_id)
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Schedule must be ACTIVE to run a cycle")
    now = db.clock.now()
    ws = parse_iso(rec["window_start"])
    we = parse_iso(rec["window_end"])
    if not (ws <= now < we):
        raise err(ERR_SCHEDULE_WINDOW_CLOSED, "Clock outside schedule window")
    campaign = db.campaigns.get(rec["campaign_id"])
    if campaign is None or campaign["status"] != "LIVE":
        raise err(ERR_CAMPAIGN_NOT_LIVE, "Funded campaign must be LIVE to run cycle")

    donation = {
        "program_id": rec["program_id"],
        "employee_id": rec["employee_id"],
        "campaign_id": rec["campaign_id"],
        "donation_type": "RECURRING",
        "funding_method": "PAYROLL_DEDUCTION",
        "base_amount_cents": rec["per_period_amount_cents"],
        "roundup_increment_cents": 0,
        "subtotal_cents": 0,
        "processing_fee_cents": 0,
        "total_charged_cents": 0,
        "tax_deductible": True,
        "schedule_id": rec["id"],
        "settled_at": None,
        "status": "PLEDGED",
    }
    stamp_create(donation)
    db.donations[donation["id"]] = donation

    rec["occurrences_generated"] += 1
    touch(rec)
    return object_response(serialize(donation), 201)
