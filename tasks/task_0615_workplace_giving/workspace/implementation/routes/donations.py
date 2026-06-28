"""Donation endpoints (PRD §3.5) including settle/refund cascades (PRD §3.6)."""
from flask import Blueprint, request

from db import db, parse_iso
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_CAMPAIGN_NOT_LIVE,
    ERR_CAMPAIGN_WINDOW_CLOSED,
    ERR_EMPLOYEE_NOT_ACTIVE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_DONATION_DISBURSED,
)
from middleware import get_user_context, require_role
from response import object_response, array_response
from services.common import (
    get_json_body,
    require_fields,
    require_string,
    require_positive_int,
    require_enum,
    optional_bool,
    stamp_create,
    touch,
    serialize,
    find_or_404,
    paginate,
)
from services.calc import donation_amount_breakdown
from services.matching import (
    create_requested_matching_gift,
    finalize_for_donation,
    reverse_for_donation,
)
from services.queries import grants_referencing_source

bp = Blueprint("donations", __name__)

DONATION_TYPES = {"ONE_TIME", "RECURRING"}
FUNDING_METHODS = {"PAYROLL_DEDUCTION", "CREDIT"}


@bp.route("/donations", methods=["POST"])
def pledge_donation():
    uid, role = get_user_context()
    require_role(role, {"Employee", "GivingAdmin"})
    body = get_json_body()
    require_fields(body, ["program_id", "employee_id", "campaign_id", "donation_type", "funding_method", "base_amount_cents"])
    program_id = require_string(body, "program_id")
    employee_id = require_string(body, "employee_id")
    campaign_id = require_string(body, "campaign_id")
    donation_type = require_enum(body, "donation_type", DONATION_TYPES)
    funding_method = require_enum(body, "funding_method", FUNDING_METHODS)
    base_amount = require_positive_int(body, "base_amount_cents")
    tax_deductible = optional_bool(body, "tax_deductible", True)
    request_match = optional_bool(body, "request_match", False)

    # Existence left-to-right (priority 4).
    find_or_404(db.programs, program_id)
    employee = find_or_404(db.employees, employee_id)
    campaign = find_or_404(db.campaigns, campaign_id)

    # Employee role ownership: X-User-ID must equal donor employee_id.
    if role == "Employee" and uid != employee_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Employee may only pledge own donations")

    # Pledge-time business checks (PRD §3.5): campaign LIVE, clock in window.
    if campaign["status"] != "LIVE":
        raise err(ERR_CAMPAIGN_NOT_LIVE, "Target campaign must be LIVE at pledge time")
    now = db.clock.now()
    ws = parse_iso(campaign["window_start"])
    we = parse_iso(campaign["window_end"])
    if not (ws <= now < we):
        raise err(ERR_CAMPAIGN_WINDOW_CLOSED, "Clock outside campaign window at pledge time")

    rec = {
        "program_id": program_id,
        "employee_id": employee_id,
        "campaign_id": campaign_id,
        "donation_type": donation_type,
        "funding_method": funding_method,
        "base_amount_cents": base_amount,
        "roundup_increment_cents": 0,
        "subtotal_cents": 0,
        "processing_fee_cents": 0,
        "total_charged_cents": 0,
        "tax_deductible": tax_deductible,
        "schedule_id": None,
        "settled_at": None,
        "status": "PLEDGED",
    }
    stamp_create(rec)
    db.donations[rec["id"]] = rec

    if request_match:
        program = db.programs.get(program_id)
        create_requested_matching_gift(program, rec, employee)

    return object_response(serialize(rec), 201)


@bp.route("/donations/<donation_id>", methods=["GET"])
def get_donation(donation_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager", "Employee"})
    rec = find_or_404(db.donations, donation_id)
    return object_response(serialize(rec), 200)


@bp.route("/donations", methods=["GET"])
def list_donations():
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager", "Employee"})
    program_id = request.args.get("program_id")
    employee_id = request.args.get("employee_id")
    campaign_id = request.args.get("campaign_id")
    schedule_id = request.args.get("schedule_id")
    status = request.args.get("status")
    items = []
    for d in db.donations.values():
        if program_id is not None and d["program_id"] != program_id:
            continue
        if employee_id is not None and d["employee_id"] != employee_id:
            continue
        if campaign_id is not None and d["campaign_id"] != campaign_id:
            continue
        if schedule_id is not None and d.get("schedule_id") != schedule_id:
            continue
        if status is not None and d["status"] != status:
            continue
        items.append(d)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(d) for d in page], limit, offset, total, 200)


@bp.route("/donations/<donation_id>/authorize", methods=["POST"])
def authorize_donation(donation_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin"})
    rec = find_or_404(db.donations, donation_id)
    if rec["status"] != "PLEDGED":
        raise err(ERR_INVALID_STATE, "Donation must be PLEDGED to authorize")
    employee = db.employees.get(rec["employee_id"])
    if employee is None or employee["status"] != "ACTIVE":
        raise err(ERR_EMPLOYEE_NOT_ACTIVE, "Donor employee must be ACTIVE")
    program = db.programs.get(rec["program_id"])
    roundup, subtotal, fee, total = donation_amount_breakdown(program, rec["base_amount_cents"])
    rec["roundup_increment_cents"] = roundup
    rec["subtotal_cents"] = subtotal
    rec["processing_fee_cents"] = fee
    rec["total_charged_cents"] = total
    rec["status"] = "AUTHORIZED"
    touch(rec)
    return object_response(serialize(rec), 200)


@bp.route("/donations/<donation_id>/settle", methods=["POST"])
def settle_donation(donation_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin"})
    rec = find_or_404(db.donations, donation_id)
    if rec["status"] != "AUTHORIZED":
        raise err(ERR_INVALID_STATE, "Donation must be AUTHORIZED to settle")
    campaign = db.campaigns.get(rec["campaign_id"])
    if campaign is None or campaign["status"] != "LIVE":
        raise err(ERR_CAMPAIGN_NOT_LIVE, "Campaign must be LIVE to settle donation")
    rec["status"] = "SETTLED"
    rec["settled_at"] = db.clock.now_iso_ms()
    touch(rec)
    # Campaign.raised_cents += base_amount_cents (mutation).
    campaign["raised_cents"] += rec["base_amount_cents"]
    touch(campaign)
    # Finalize linked matching gift if still REQUESTED.
    finalize_for_donation(rec)
    return object_response(serialize(rec), 200)


@bp.route("/donations/<donation_id>/cancel", methods=["POST"])
def cancel_donation(donation_id):
    uid, role = get_user_context()
    require_role(role, {"Employee"})
    rec = find_or_404(db.donations, donation_id)
    # Owner check (priority 3).
    if uid != rec["employee_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER, "Employee may only cancel own donation")
    if rec["status"] != "PLEDGED":
        raise err(ERR_INVALID_STATE, "Donation must be PLEDGED to cancel")
    rec["status"] = "CANCELLED"
    touch(rec)
    return object_response(serialize(rec), 200)


@bp.route("/donations/<donation_id>/refund", methods=["POST"])
def refund_donation(donation_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin"})
    rec = find_or_404(db.donations, donation_id)
    if rec["status"] != "SETTLED":
        raise err(ERR_INVALID_STATE, "Donation must be SETTLED to refund")
    # No Grant references this donation in {STAGED, SETTLED}.
    if grants_referencing_source("DONATION", donation_id, {"STAGED", "SETTLED"}):
        raise err(ERR_DONATION_DISBURSED, "Cannot refund a donation whose grant is staged or settled")
    rec["status"] = "REFUNDED"
    touch(rec)
    campaign = db.campaigns.get(rec["campaign_id"])
    if campaign is not None:
        campaign["raised_cents"] -= rec["base_amount_cents"]
        touch(campaign)
    # Reverse linked FINALIZED matching gift (compensating).
    reverse_for_donation(rec)
    return object_response(serialize(rec), 200)
