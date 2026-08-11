"""RatificationVote endpoints: create, open, tally with outcome cascades."""

from flask import Blueprint, request

import calc
import clock
from db import db
from errors import (
    ERR_BALLOT_STILL_OPEN,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NO_ACCEPTED_PACKAGE,
    ERR_NO_LOCKED_SCENARIO,
    ERR_UNION_MISMATCH,
    raise_err,
)
from helpers import (
    ALL_ROLES, authenticate, get_body, lookup, new_entity, page, parse_pagination,
    req_datetime, req_int, req_string, serialize, sort_items, touch,
)
from response import success_list, success_object
from services import ratified_cascade, rejected_cascade

bp = Blueprint("votes", __name__)

VOTE_STATUSES = ("SCHEDULED", "OPEN", "RATIFIED", "REJECTED")


@bp.post("/labor-relations/ratification-votes")
def create_vote():
    authenticate(["ChiefNegotiator"])
    body = get_body()
    agreement_id = req_string(body, "agreement_id")
    eligible_voter_count = req_int(body, "eligible_voter_count")
    if eligible_voter_count < 1:
        raise_err(ERR_INVALID_REQUEST, "eligible_voter_count must be >= 1")
    ballot_close_at = req_datetime(body, "ballot_close_at")

    agreement = lookup(db.agreements, agreement_id, "CollectiveAgreement")
    if agreement["status"] in ("ARCHIVED", "REPLACED"):
        raise_err(ERR_INVALID_STATE, "Cannot create a vote on a %s agreement" % agreement["status"])

    vote = new_entity()
    vote.update({
        "agreement_id": agreement_id,
        "eligible_voter_count": eligible_voter_count,
        "ballot_close_at": ballot_close_at,
        "status": "SCHEDULED",
        "opened_by_user_id": None,
        "votes_for": None,
        "votes_against": None,
        "votes_cast": None,
        "quorum_met": None,
        "retro_payout_cents": None,
    })
    db.votes[vote["id"]] = vote
    return success_object(serialize(vote), status=201)


@bp.get("/labor-relations/ratification-votes")
def list_votes():
    authenticate(ALL_ROLES)
    limit, offset = parse_pagination()
    agreement_id = request.args.get("agreement_id")
    status = request.args.get("status")
    items = list(db.votes.values())
    if agreement_id is not None:
        items = [v for v in items if v["agreement_id"] == agreement_id]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    items = sort_items(items)
    slice_, total = page(items, limit, offset)
    return success_list([serialize(v) for v in slice_], limit, offset, total)


@bp.get("/labor-relations/ratification-votes/<vote_id>")
def get_vote(vote_id):
    authenticate(ALL_ROLES)
    vote = lookup(db.votes, vote_id, "RatificationVote")
    return success_object(serialize(vote))


@bp.post("/labor-relations/ratification-votes/<vote_id>/state")
def open_vote(vote_id):
    user_id, role = authenticate(["ChiefNegotiator"])
    vote = lookup(db.votes, vote_id, "RatificationVote")
    body = get_body()
    to_status = req_string(body, "to_status")
    if to_status not in VOTE_STATUSES:
        raise_err(ERR_INVALID_REQUEST, "Unknown vote status: %s" % to_status)
    if to_status != "OPEN":
        raise_err(ERR_INVALID_STATE, "Only the OPEN transition is available on this endpoint")

    if vote["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Only a SCHEDULED vote can be opened")
    if vote["ballot_close_at"] <= clock.now():
        raise_err(ERR_INVALID_STATE, "ballot_close_at is not in the future")
    agreement = lookup(db.agreements, vote["agreement_id"], "CollectiveAgreement")
    has_locked = any(s["agreement_id"] == vote["agreement_id"] and s["status"] == "LOCKED"
                     for s in db.scenarios.values())
    if not has_locked:
        raise_err(ERR_NO_LOCKED_SCENARIO, "No LOCKED costing scenario exists for this agreement")
    has_accepted = any(p["agreement_id"] == vote["agreement_id"] and p["status"] == "ACCEPTED"
                       for p in db.proposals.values())
    if not has_accepted:
        raise_err(ERR_NO_ACCEPTED_PACKAGE, "No ACCEPTED proposal exists for this agreement")

    vote["opened_by_user_id"] = user_id
    vote["status"] = "OPEN"
    touch(vote)
    return success_object(serialize(vote))


@bp.post("/labor-relations/ratification-votes/<vote_id>/tally")
def tally_vote(vote_id):
    user_id, role = authenticate(["UnionRepresentative"])
    vote = lookup(db.votes, vote_id, "RatificationVote")
    agreement = lookup(db.agreements, vote["agreement_id"], "CollectiveAgreement")
    if user_id != agreement["union_id"]:
        raise_err(ERR_UNION_MISMATCH, "X-User-ID does not match the vote agreement's union_id")
    body = get_body()
    votes_for = req_int(body, "votes_for")
    votes_against = req_int(body, "votes_against")
    if votes_for < 0 or votes_against < 0:
        raise_err(ERR_INVALID_REQUEST, "vote counts must be >= 0")

    if vote["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "Only an OPEN vote can be tallied")
    if clock.now() < vote["ballot_close_at"]:
        raise_err(ERR_BALLOT_STILL_OPEN, "The ballot has not closed yet")

    votes_cast, quorum_met, ratified = calc.ratification_outcome(vote, votes_for, votes_against)
    vote["votes_for"] = votes_for
    vote["votes_against"] = votes_against
    vote["votes_cast"] = votes_cast
    vote["quorum_met"] = quorum_met

    if ratified:
        vote["status"] = "RATIFIED"
        implemented = ratified_cascade(vote, agreement)
        vote["retro_payout_cents"] = calc.retro_payout(agreement, implemented, clock.now())
    else:
        vote["status"] = "REJECTED"
        vote["retro_payout_cents"] = 0
        rejected_cascade(agreement)

    touch(vote)
    return success_object(serialize(vote))
