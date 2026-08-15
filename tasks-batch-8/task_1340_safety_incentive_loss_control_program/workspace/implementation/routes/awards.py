"""Incentive awards and the point-ledger events (PRD 3.8)."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import auth, paginate, NON_CONTRACTOR_ROLES
from response import ok, ok_list
from services import core

bp = Blueprint("awards", __name__)


@bp.route("/safety/incentive-awards", methods=["GET"])
def list_awards():
    auth(NON_CONTRACTOR_ROLES)
    program_id = request.args.get("program_id")
    employee_id = request.args.get("employee_id")
    status = request.args.get("status")
    tier = request.args.get("tier")
    items = list(db.DB["awards"].values())
    if program_id is not None:
        items = [a for a in items if a["program_id"] == program_id]
    if employee_id is not None:
        items = [a for a in items if a["employee_id"] == employee_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if tier is not None:
        items = [a for a in items if a["tier"] == tier]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.award_view(a) for a in page], total, limit, offset)


@bp.route("/safety/incentive-awards/<aid>", methods=["GET"])
def get_award(aid):
    auth(NON_CONTRACTOR_ROLES)
    a = core.get_or_404("awards", aid, "IncentiveAward")
    return ok(core.award_view(a))


@bp.route("/safety/incentive-awards/<aid>/approve", methods=["POST"])
def approve_award(aid):
    auth(["EHSAdmin"])
    a = core.get_or_404("awards", aid, "IncentiveAward")
    core.body_json()
    p = db.DB["programs"].get(a["program_id"])
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "SafetyProgram not found")
    if p["status"] != "CLOSED":
        raise ApiError("ERR_PROGRAM_NOT_CLOSED", 409,
                       "Awards can be approved only while the program is CLOSED")
    # State beats fiscal (validations priority 5 < 23).
    if a["status"] != "CALCULATED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a CALCULATED award can be approved")
    if p["remaining_budget_cents"] < a["payout_cents"]:
        raise ApiError("ERR_INCENTIVE_BUDGET_EXCEEDED", 422,
                       "The program's remaining incentive budget cannot cover "
                       "this payout")
    a["status"] = "APPROVED"
    core.touch(a)
    p["remaining_budget_cents"] -= a["payout_cents"]
    core.touch(p)
    return ok(core.award_view(a))


@bp.route("/safety/incentive-awards/<aid>/pay", methods=["POST"])
def pay_award(aid):
    auth(["EHSAdmin"])
    a = core.get_or_404("awards", aid, "IncentiveAward")
    core.body_json()
    if a["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an APPROVED award can be paid")
    a["status"] = "PAID"
    core.touch(a)
    return ok(core.award_view(a))


@bp.route("/safety/incentive-awards/<aid>/void", methods=["POST"])
def void_award(aid):
    auth(["EHSAdmin"])
    a = core.get_or_404("awards", aid, "IncentiveAward")
    body = core.body_json()
    reason = core.req_str(body, "void_reason")
    if a["status"] not in ("CALCULATED", "APPROVED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a CALCULATED or APPROVED award can be voided")
    if a["status"] == "APPROVED":
        # Compensation: voiding an approved award restores the reservation.
        p = db.DB["programs"].get(a["program_id"])
        if p is not None:
            p["remaining_budget_cents"] += a["payout_cents"]
            core.touch(p)
    a["status"] = "VOIDED"
    a["void_reason"] = reason
    core.touch(a)
    return ok(core.award_view(a))


@bp.route("/safety/incentive-events", methods=["GET"])
def list_events():
    auth(NON_CONTRACTOR_ROLES)
    program_id = request.args.get("program_id")
    employee_id = request.args.get("employee_id")
    source_type = request.args.get("source_type")
    items = list(db.DB["events"].values())
    if program_id is not None:
        items = [e for e in items if e["program_id"] == program_id]
    if employee_id is not None:
        items = [e for e in items if e["employee_id"] == employee_id]
    if source_type is not None:
        items = [e for e in items if e["source_type"] == source_type]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.event_view(e) for e in page], total, limit, offset)


@bp.route("/safety/incentive-events/<eid>", methods=["GET"])
def get_event(eid):
    auth(NON_CONTRACTOR_ROLES)
    e = core.get_or_404("events", eid, "IncentiveEvent")
    return ok(core.event_view(e))
