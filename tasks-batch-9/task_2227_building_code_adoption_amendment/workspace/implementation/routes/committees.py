"""Discipline committees and committee members (PRD 3.1)."""
from flask import Blueprint

import config
import db
import middleware
import response
import validate
from errors import ApiError
from routes.common import apply_filters, as_str, paged
from services import derive, lookup, serialize

bp = Blueprint("committees", __name__)


@bp.get("/discipline-committees")
def list_committees():
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    rows = apply_filters(list(db.discipline_committees.values()), {
        "code_cycle_id": ("code_cycle_id", as_str),
        "discipline": ("discipline", as_str),
        "status": ("status", as_str),
    })
    return paged(rows, serialize.discipline_committee, limit, offset)


@bp.get("/discipline-committees/<committee_id>")
def get_committee(committee_id):
    middleware.require(config.ALL_ROLES)
    record = lookup.committee(committee_id)
    return response.object_response(serialize.discipline_committee(record))


@bp.post("/discipline-committees/<committee_id>/members")
def create_member(committee_id):
    middleware.require((config.ROLE_COUNCIL_ADMIN,))
    body = validate.body()
    full_name = validate.req_string(body, "full_name")
    sector = validate.req_enum(body, "sector", config.SECTORS)
    voting_seat = validate.opt_bool(body, "voting_seat", True)
    is_chair = validate.opt_bool(body, "is_chair", False)
    committee = lookup.committee(committee_id)

    if is_chair and derive.chair_member_count(committee["id"]) >= 1:
        raise ApiError("ERR_CHAIR_ALREADY_SEATED")
    if voting_seat:
        if derive.active_voting_member_count(committee["id"]) + 1 > committee["voting_seat_count"]:
            raise ApiError("ERR_SEAT_LIMIT_EXCEEDED")

    record = db.new_record({
        "committee_id": committee["id"],
        "full_name": full_name,
        "sector": sector,
        "voting_seat": voting_seat,
        "is_chair": is_chair,
        "status": "ACTIVE",
        "recusal_reason": None,
    })
    db.committee_members[record["id"]] = record
    derive.refresh_committee_seating(committee)
    return response.object_response(serialize.committee_member(record), 201)


@bp.get("/discipline-committees/<committee_id>/members")
def list_committee_members(committee_id):
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    committee = lookup.committee(committee_id)
    rows = derive.committee_members_of(committee["id"])
    return paged(rows, serialize.committee_member, limit, offset)


@bp.get("/discipline-committees/<committee_id>/amendment-proposals")
def list_committee_proposals(committee_id):
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    committee = lookup.committee(committee_id)
    rows = derive.children(db.amendment_proposals, "committee_id", committee["id"])
    return paged(rows, serialize.amendment_proposal, limit, offset)


@bp.get("/discipline-committees/<committee_id>/hearings")
def list_committee_hearings(committee_id):
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    committee = lookup.committee(committee_id)
    rows = derive.children(db.hearings, "committee_id", committee["id"])
    return paged(rows, serialize.hearing, limit, offset)


@bp.get("/discipline-committees/<committee_id>/interpretation-requests")
def list_committee_interpretations(committee_id):
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    committee = lookup.committee(committee_id)
    rows = derive.children(db.interpretation_requests, "assigned_committee_id", committee["id"])
    return paged(rows, serialize.interpretation_request, limit, offset)


@bp.get("/committee-members")
def list_members():
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    rows = apply_filters(list(db.committee_members.values()), {
        "committee_id": ("committee_id", as_str),
        "sector": ("sector", as_str),
        "status": ("status", as_str),
    })
    return paged(rows, serialize.committee_member, limit, offset)


@bp.get("/committee-members/<member_id>")
def get_member(member_id):
    middleware.require(config.ALL_ROLES)
    record = lookup.member(member_id)
    return response.object_response(serialize.committee_member(record))


@bp.post("/committee-members/<member_id>/recusal")
def set_recusal(member_id):
    middleware.require((config.ROLE_COUNCIL_ADMIN,))
    body = validate.body()
    action = validate.req_enum(body, "action", ("RECUSE", "REINSTATE"))
    recusal_reason = validate.opt_string(body, "recusal_reason")
    member = lookup.member(member_id)

    if action == "RECUSE":
        member["status"] = "RECUSED"
        member["recusal_reason"] = recusal_reason
    else:
        member["status"] = "ACTIVE"
        member["recusal_reason"] = None
    db.touch(member)

    committee = db.discipline_committees.get(member["committee_id"])
    if committee is not None:
        derive.refresh_committee_seating(committee)

    return response.object_response(serialize.committee_member(member))
