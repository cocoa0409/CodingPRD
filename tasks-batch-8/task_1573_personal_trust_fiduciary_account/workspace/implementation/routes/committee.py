"""CommitteeMember CRUD + deactivation; CommitteeVote reads."""

from flask import Blueprint, request

import db
from errors import ApiError, ERR_INVALID_STATE
from middleware import authenticate, require_role
from response import ok, ok_list
from serialize import committee_member_json, vote_json
from services import workflow
from services.workflow import find_or_404
from validation import get_body, validate, parse_pagination

bp = Blueprint("committee", __name__)

READ_ROLES = {"TrustOfficer", "TrustExecutive", "InvestmentManager",
              "TrustOperationsOfficer", "TaxSpecialist", "CommitteeMember"}
VOTE_READ_ROLES = {"TrustOfficer", "TrustExecutive", "CommitteeMember"}


@bp.route("/trusts/committee-members", methods=["POST"])
def create_member():
    _, role = authenticate()
    data = get_body()
    v = validate(data, [
        ("full_name", "str", True),
        ("term_start", "date", True),
        ("term_end", "date", True),
    ])
    require_role(role, {"TrustExecutive"})
    m = workflow.new_entity()
    m.update({
        "full_name": v["full_name"],
        "term_start": v["term_start"],
        "term_end": v["term_end"],
        "status": "ACTIVE",
    })
    db.committee_members[m["id"]] = m
    return ok(committee_member_json(m), status=201)


@bp.route("/trusts/committee-members", methods=["GET"])
def list_members():
    _, role = authenticate()
    limit, offset = parse_pagination()
    require_role(role, READ_ROLES)
    filters = []
    status = request.args.get("status")
    if status is not None:
        filters.append(("status", status))
    items, total = workflow.list_page(db.committee_members, filters,
                                      committee_member_json, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/trusts/committee-members/<mid>", methods=["GET"])
def get_member(mid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    m = find_or_404(db.committee_members, mid, "CommitteeMember")
    return ok(committee_member_json(m))


@bp.route("/trusts/committee-members/<mid>/deactivate", methods=["POST"])
def deactivate_member(mid):
    _, role = authenticate()
    get_body()
    require_role(role, {"TrustExecutive"})
    m = find_or_404(db.committee_members, mid, "CommitteeMember")
    if m["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "CommitteeMember must be ACTIVE to deactivate")
    m["status"] = "INACTIVE"
    workflow.touch(m)
    return ok(committee_member_json(m))


@bp.route("/trusts/votes", methods=["GET"])
def list_votes():
    _, role = authenticate()
    limit, offset = parse_pagination()
    require_role(role, VOTE_READ_ROLES)
    filters = []
    for param in ("distribution_request_id", "committee_member_id"):
        val = request.args.get(param)
        if val is not None:
            filters.append((param, val))
    items, total = workflow.list_page(db.votes, filters, vote_json, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/trusts/votes/<vid>", methods=["GET"])
def get_vote(vid):
    _, role = authenticate()
    require_role(role, VOTE_READ_ROLES)
    v = find_or_404(db.votes, vid, "CommitteeVote")
    return ok(vote_json(v))
