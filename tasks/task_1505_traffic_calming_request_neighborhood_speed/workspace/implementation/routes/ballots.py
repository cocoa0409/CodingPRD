"""Ballots and votes (PRD §3.6)."""
from flask import Blueprint, g, request

from auth import require_roles, ALL_ROLES
from envelope import object_response
from errors import (
    ApiError, ERR_BALLOT_INVALID_STATE, ERR_HOUSEHOLD_NOT_ON_SEGMENT,
    ERR_DUPLICATE_BALLOT_VOTE,
)
from helpers import get_ballot, paginated, recompute_vote_counts
from store import store, touch
from validate import parse_body, Struct

bp = Blueprint("ballots", __name__)

CHOICES = ("FOR", "AGAINST")


@bp.get("/api/ballots/<ballotId>")
@require_roles(*ALL_ROLES)
def get_one(ballotId):
    return object_response(get_ballot(ballotId))


@bp.get("/api/ballots")
@require_roles(*ALL_ROLES)
def list_ballots():
    return paginated(list(store.ballots.values()), {
        "request_id": request.args.get("request_id"),
        "treatment_plan_id": request.args.get("treatment_plan_id"),
        "status": request.args.get("status"),
    })


@bp.post("/api/ballots/<ballotId>/votes")
@require_roles("Resident")
def cast_vote(ballotId):
    ballot = get_ballot(ballotId)
    data, perr = parse_body()
    s = Struct(data, perr)
    choice = s.get_enum("choice", CHOICES)
    # Tier 5: ballot must still be OPEN (the clock sweep tallies it atomically
    # once the logical clock passes close_date)
    if ballot["status"] != "OPEN":
        raise ApiError(409, ERR_BALLOT_INVALID_STATE,
                       "The ballot is not open for voting")
    # Tier 8: structural
    s.raise_if_errors()
    resident = g.resident
    req = store.requests[ballot["request_id"]]
    if resident["street_segment_id"] != req["street_segment_id"]:
        raise ApiError(422, ERR_HOUSEHOLD_NOT_ON_SEGMENT,
                       "The voter's household does not front the ballot's segment")
    for v in store.votes.values():
        if v["ballot_id"] == ballotId and v["household_ref"] == resident["household_ref"]:
            raise ApiError(409, ERR_DUPLICATE_BALLOT_VOTE,
                           "A vote for this household already exists on this ballot")
    vote = {
        "id": store.new_id(),
        "ballot_id": ballotId,
        "resident_id": g.user_id,
        "household_ref": resident["household_ref"],
        "choice": choice,
        "cast_at": store.now,
        "created_at": store.now,
        "_seq": store.next_seq(),
    }
    store.votes[vote["id"]] = vote
    recompute_vote_counts(ballot)
    touch(ballot)
    return object_response(vote, 201)


@bp.get("/api/ballots/<ballotId>/votes")
@require_roles(*ALL_ROLES)
def list_votes(ballotId):
    get_ballot(ballotId)
    items = [v for v in store.votes.values() if v["ballot_id"] == ballotId]
    return paginated(items)
