"""Member enrollment and lifecycle (PRD §3.2)."""

from flask import Blueprint

import db
from db import store, new_entity, touch, public
from errors import err_not_found, err_state, err_invalid_request, ApiError, ERR_OPEN_CLAWBACK
from middleware import require_roles, body_json, req_str
from response import success_object, success_list, parse_pagination, paginate
from services import calc

bp = Blueprint("members", __name__)

COMMITMENT_LEVELS = ("BUILDER", "STANDARD", "PLATINUM")
READ_ROLES = ("CoopAdmin", "FinanceOfficer", "ProgramAuditor", "MemberRep")
LIST_ROLES = ("CoopAdmin", "FinanceOfficer", "ProgramAuditor")


def _get_member(member_id):
    member = store.members.get(member_id)
    if member is None:
        raise err_not_found("Member not found")
    return member


def _member_enrollments(member_id):
    return [e for e in store.enrollments.values() if e["member_id"] == member_id]


@bp.route("/coop/members", methods=["POST"])
@require_roles("CoopAdmin")
def create_member(uid, role):
    body = body_json(required=True)
    legal_name = req_str(body, "legal_name")
    commitment_level = req_str(body, "commitment_level")
    if commitment_level not in COMMITMENT_LEVELS:
        raise err_invalid_request("commitment_level must be BUILDER, STANDARD, or PLATINUM")
    member = new_entity()
    member.update({
        "legal_name": legal_name,
        "commitment_level": commitment_level,
        "status": "PENDING",
        "enrolled_quarter_index": None,
        "churn_quarter_index": None,
        "lifetime_pass_through_cents": 0,
        "lifetime_clawback_cents": 0,
        "prior_audit_findings_count": 0,
    })
    store.members[member["id"]] = member
    return success_object(public(member), code=201)


@bp.route("/coop/members/<member_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_member(uid, role, member_id):
    return success_object(public(_get_member(member_id)), code=200)


@bp.route("/coop/members", methods=["GET"])
@require_roles(*LIST_ROLES)
def list_members(uid, role):
    limit, offset = parse_pagination()
    items = list(store.members.values())
    status = request_arg("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    commitment = request_arg("commitment_level")
    if commitment is not None:
        items = [m for m in items if m["commitment_level"] == commitment]
    page, total = paginate(items, limit, offset)
    return success_list([public(m) for m in page], limit, offset, total)


def request_arg(name):
    from flask import request
    v = request.args.get(name)
    return v if v not in (None, "") else None


@bp.route("/coop/members/<member_id>/activate", methods=["POST"])
@require_roles("CoopAdmin")
def activate_member(uid, role, member_id):
    member = _get_member(member_id)
    if member["status"] != "PENDING":
        raise err_state("Only a PENDING member can be activated")
    member["status"] = "ACTIVE"
    member["enrolled_quarter_index"] = db.get_coop()["current_quarter_index"]
    touch(member)
    return success_object(public(member), code=200)


@bp.route("/coop/members/<member_id>/suspend", methods=["POST"])
@require_roles("CoopAdmin")
def suspend_member(uid, role, member_id):
    member = _get_member(member_id)
    if member["status"] != "ACTIVE":
        raise err_state("Only an ACTIVE member can be suspended")
    for enr in _member_enrollments(member["id"]):
        if enr["status"] == "ACTIVE":
            enr["status"] = "SUSPENDED"
            touch(enr)
    member["status"] = "SUSPENDED"
    touch(member)
    return success_object(public(member), code=200)


@bp.route("/coop/members/<member_id>/reinstate", methods=["POST"])
@require_roles("CoopAdmin")
def reinstate_member(uid, role, member_id):
    member = _get_member(member_id)
    if member["status"] != "SUSPENDED":
        raise err_state("Only a SUSPENDED member can be reinstated")
    open_cases = [c for c in store.clawbacks.values()
                  if c["member_id"] == member["id"]
                  and c["status"] in ("OPEN", "NOTIFIED", "DISPUTED")]
    if open_cases:
        raise ApiError(ERR_OPEN_CLAWBACK, 409,
                       "Member has an unresolved clawback case")
    for enr in _member_enrollments(member["id"]):
        if enr["status"] == "SUSPENDED":
            enr["status"] = "ACTIVE"
            touch(enr)
    member["status"] = "ACTIVE"
    touch(member)
    return success_object(public(member), code=200)


@bp.route("/coop/members/<member_id>/churn", methods=["POST"])
@require_roles("CoopAdmin")
def churn_member(uid, role, member_id):
    member = _get_member(member_id)
    if member["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err_state("Only an ACTIVE or SUSPENDED member can be churned")
    coop = db.get_coop()
    current = coop["current_quarter_index"]
    member["churn_quarter_index"] = current
    for enr in _member_enrollments(member["id"]):
        if enr["status"] in ("ACTIVE", "SUSPENDED"):
            enr["status"] = "EXITED"
            enr["exit_quarter_index"] = current
            touch(enr)
    # Waterfall: gross over DISTRIBUTED accruals, forfeit SCHEDULED holdbacks
    # first, then net floored at zero (PRD §3.7).
    calc.create_clawback_case(member["id"], "CHURN")
    member["status"] = "CHURNED"
    touch(member)
    return success_object(public(member), code=200)
