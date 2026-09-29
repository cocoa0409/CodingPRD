"""Ballot casting, recasting and revocation (PRD 3.5, 2.9)."""

from flask import Blueprint

import response as R
import validation as V
from db import by_seq, db, new_row, now_dt, now_iso, parse_datetime, touch
from errors import ApiError
from middleware import actor_id, auth
from services import constants as C
from services import state as S

bp = Blueprint("ballots", __name__)

READERS = ("AssociationSecretary", "BoardTreasurer", "MemberOwner")


@bp.post("/ballots")
@auth("MemberOwner")
def cast_ballot():
    body = V.get_body()
    proposal_id = V.req_str(body, "proposal_id")
    member_id = V.req_str(body, "member_id")
    choice = V.req_enum(body, "choice", C.BALLOT_CHOICES)
    expected_version = V.req_int(body, "expected_proposal_version", minimum=0)

    proposal = S.require("proposal", proposal_id)
    member = S.require("member", member_id)

    if member_id != actor_id():
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "A member may only cast their own ballot.")
    if expected_version != proposal["version"]:
        raise ApiError("ERR_STALE_PROPOSAL_VERSION",
                       "expected_proposal_version does not match the proposal's current version.")
    if proposal["status"] != "BALLOTING":
        raise ApiError("ERR_PROPOSAL_NOT_BALLOTING", "The proposal is not accepting ballots.")

    parcel = db.parcels.get(member["parcel_id"])
    if parcel is None or parcel["covenant_recorded"] is not True:
        raise ApiError("ERR_COVENANT_NOT_RECORDED",
                       "The voting member's parcel has no recorded covenant.")

    closes_at = parse_datetime(proposal["balloting_closes_at"])
    if closes_at is not None and now_dt() >= closes_at:
        raise ApiError("ERR_BALLOTING_CLOSED", "The balloting round has closed.")

    if member["standing_status"] != "GOOD_STANDING":
        raise ApiError("ERR_MEMBER_NOT_IN_GOOD_STANDING",
                       "Only a member in GOOD_STANDING may cast a ballot.")

    for prior in S.ballots_of_proposal(proposal["id"]):
        if prior["member_id"] == member_id and prior["status"] == "CAST":
            prior["status"] = "SUPERSEDED"
            touch(prior)

    row = new_row({
        "proposal_id": proposal["id"],
        "member_id": member_id,
        "choice": choice,
        "weight_snapshot": S.voting_weight(member, proposal["voting_basis"]),
        "status": "CAST",
        "cast_at": now_iso(),
    })
    db.ballots[row["id"]] = row

    S.recompute_tally(proposal)
    touch(proposal)
    return R.ok(row, 201)


@bp.get("/ballots/<ballot_id>")
@auth(*READERS)
def read_ballot(ballot_id):
    return R.ok(S.require("ballot", ballot_id))


@bp.get("/ballots")
@auth(*READERS)
def list_ballots():
    limit, offset = V.pagination()
    proposal_id = V.query_str("proposal_id")
    member_id = V.query_str("member_id")
    status = V.query_enum("status", C.BALLOT_STATUSES)

    rows = by_seq(list(db.ballots.values()))
    if proposal_id is not None:
        rows = [r for r in rows if r["proposal_id"] == proposal_id]
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = V.paginate(rows, limit, offset)
    return R.ok_list(page, limit, offset, total)


@bp.post("/ballots/<ballot_id>/revoke")
@auth("MemberOwner")
def revoke_ballot(ballot_id):
    body = V.get_body()
    expected_version = V.req_int(body, "expected_proposal_version", minimum=0)

    ballot = S.require("ballot", ballot_id)

    if ballot["member_id"] != actor_id():
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "A member may only revoke their own ballot.")

    proposal = db.proposals.get(ballot["proposal_id"])
    if proposal is None:
        raise ApiError("ERR_PROPOSAL_NOT_FOUND", "The ballot's proposal does not resolve.")

    if expected_version != proposal["version"]:
        raise ApiError("ERR_STALE_PROPOSAL_VERSION",
                       "expected_proposal_version does not match the proposal's current version.")
    if proposal["status"] != "BALLOTING":
        raise ApiError("ERR_PROPOSAL_NOT_BALLOTING", "The proposal is not in a balloting round.")
    if ballot["status"] != "CAST":
        raise ApiError("ERR_BALLOT_NOT_CAST", "Only a CAST ballot may be revoked.")

    closes_at = parse_datetime(proposal["balloting_closes_at"])
    if closes_at is not None and now_dt() >= closes_at:
        raise ApiError("ERR_BALLOTING_CLOSED", "The balloting round has closed.")

    ballot["status"] = "REVOKED"
    touch(ballot)

    S.recompute_tally(proposal)
    touch(proposal)
    return R.ok(ballot)
