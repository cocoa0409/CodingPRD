"""Claim records (PRD 3.6): report, accept, deny, close."""

from flask import Blueprint, request

import db
from clock import CLOCK
from errors import ApiError
from middleware import auth, paginate, NON_CONTRACTOR_ROLES
from response import ok, ok_list
from services import calc, core

bp = Blueprint("claims", __name__)


@bp.route("/safety/claims", methods=["POST"])
def create_claim():
    auth(["SafetyManager", "EHSAdmin"])
    body = core.body_json()
    program_id = core.req_str(body, "program_id")
    occurred_on = core.req_date(body, "occurred_on")
    kind = core.req_enum(body, "kind", ("MEDICAL_ONLY", "INDEMNITY"))
    incurred = core.req_int(body, "incurred_cents", minimum=0)
    employee_id = core.opt_str(body, "employee_id", default=None)
    contractor_org_id = core.opt_str(body, "contractor_org_id", default=None)
    core.get_or_404("programs", program_id, "SafetyProgram")
    if employee_id is not None:
        core.get_or_404("employees", employee_id, "Employee")
    if contractor_org_id is not None:
        core.get_or_404("contractors", contractor_org_id, "ContractorOrg")
    if occurred_on > CLOCK.today():
        raise ApiError("ERR_FUTURE_DATE_NOT_ALLOWED", 422,
                       "occurred_on must not be in the future")
    c = core.stamp_new({
        "id": core.new_id(),
        "program_id": program_id,
        "employee_id": employee_id,
        "contractor_org_id": contractor_org_id,
        "occurred_on": occurred_on.isoformat(),
        "kind": kind,
        "incurred_cents": incurred,
        "effective_incurred_cents": calc.effective_incurred(kind, incurred),
        "status": "REPORTED",
    })
    db.DB["claims"][c["id"]] = c
    return ok(core.claim_view(c), 201)


@bp.route("/safety/claims", methods=["GET"])
def list_claims():
    auth(NON_CONTRACTOR_ROLES)
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    kind = request.args.get("kind")
    employee_id = request.args.get("employee_id")
    contractor_org_id = request.args.get("contractor_org_id")
    items = list(db.DB["claims"].values())
    if program_id is not None:
        items = [c for c in items if c["program_id"] == program_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if kind is not None:
        items = [c for c in items if c["kind"] == kind]
    if employee_id is not None:
        items = [c for c in items if c["employee_id"] == employee_id]
    if contractor_org_id is not None:
        items = [c for c in items if c["contractor_org_id"] == contractor_org_id]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.claim_view(c) for c in page], total, limit, offset)


@bp.route("/safety/claims/<cid>", methods=["GET"])
def get_claim(cid):
    auth(NON_CONTRACTOR_ROLES)
    c = core.get_or_404("claims", cid, "ClaimRecord")
    return ok(core.claim_view(c))


@bp.route("/safety/claims/<cid>/accept", methods=["POST"])
def accept_claim(cid):
    auth(["SafetyManager"])
    c = core.get_or_404("claims", cid, "ClaimRecord")
    body = core.body_json()
    new_incurred = core.opt_int(body, "incurred_cents", default=None, minimum=0)
    if c["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a REPORTED claim can be accepted")
    if new_incurred is not None:
        c["incurred_cents"] = new_incurred
        c["effective_incurred_cents"] = calc.effective_incurred(
            c["kind"], new_incurred)
    c["status"] = "ACCEPTED"
    core.touch(c)
    return ok(core.claim_view(c))


@bp.route("/safety/claims/<cid>/deny", methods=["POST"])
def deny_claim(cid):
    auth(["SafetyManager"])
    c = core.get_or_404("claims", cid, "ClaimRecord")
    body = core.body_json()
    core.req_str(body, "reason")
    if c["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a REPORTED claim can be denied")
    c["status"] = "DENIED"
    core.touch(c)
    return ok(core.claim_view(c))


@bp.route("/safety/claims/<cid>/close", methods=["POST"])
def close_claim(cid):
    auth(["SafetyManager"])
    c = core.get_or_404("claims", cid, "ClaimRecord")
    body = core.body_json()
    final = core.opt_int(body, "final_incurred_cents", default=None, minimum=0)
    if c["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ACCEPTED claim can be closed")
    if final is not None:
        c["incurred_cents"] = final
        c["effective_incurred_cents"] = calc.effective_incurred(c["kind"], final)
    c["status"] = "CLOSED"
    core.touch(c)
    return ok(core.claim_view(c))
