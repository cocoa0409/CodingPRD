"""Voting, revision and negative adjudication (PRD 3.4, 3.5)."""

from flask import Blueprint

from core import auth, envelope
from core.enums import ADJUDICATION_RESOLUTION, VOTE_POSITION, VOTE_STATUS
from core.errors import bad_request, fail
from core.store import db, insert, now, now_iso, public, rows, touch
from core.validation import Body, apply_filters, load_fk, load_path, non_empty
from services import ballots as ballot_service, graph

bp = Blueprint("votes", __name__)

FILTERS = ("ballot_id", "membership_id", "adjudicated_by_participant_id", "position",
           "status", "adjudication_status")


def _objection_comment(vote, ballot, comment_text, clause_reference):
    """The server files the objection itself; a client may never post a
    BALLOT_NEGATIVE comment."""
    return insert("comments", {
        "draft_id": ballot["draft_id"],
        "ballot_id": ballot["id"],
        "public_review_id": None,
        "source_vote_id": vote["id"],
        "submitter_participant_id": auth.caller_id(),
        "source_type": "BALLOT_NEGATIVE",
        "comment_type": "TECHNICAL",
        "comment_text": comment_text,
        "clause_reference": clause_reference,
        "is_substantive": True,
        "status": "OPEN",
        "disposition_rationale": None,
    })


@bp.post("/sdo/ballots/<ballot_id>/votes")
def cast_vote(ballot_id):
    auth.authenticate((auth.COMMITTEE_MEMBER, auth.COMMITTEE_CHAIR))
    ballot = load_path("ballots", ballot_id)
    body = Body(("membership_id", "position", "comment_text", "clause_reference"))
    membership_id = body.id_ref("membership_id", required=True)
    position = body.enum("position", VOTE_POSITION, required=True)
    comment_text = body.string("comment_text", min_len=1, max_len=2000,
                               nullable=True, default=None)
    clause_reference = body.string("clause_reference", min_len=1, max_len=40,
                                   nullable=True, default=None)

    seat = load_fk("memberships", membership_id, optional=False)
    auth.require_actor_identity(seat["participant_id"])

    if ballot["status"] != "OPEN":
        fail("ERR_BALLOT_NOT_OPEN", "The ballot is not OPEN.")

    if position == "NEGATIVE" and not non_empty(comment_text):
        fail("ERR_NEGATIVE_REQUIRES_COMMENT",
             "A negative vote must carry a non-empty comment_text.")

    for existing in graph.votes_of_ballot(ballot):
        if existing["membership_id"] == membership_id and existing["status"] == "CAST":
            fail("ERR_DUPLICATE_VOTE", "This seat has already returned a vote.")

    eligible = (seat["committee_id"] == ballot["committee_id"]
                and seat["status"] == "ACTIVE"
                and seat["voting_rights"] is True)
    if eligible and ballot["effective_ballot_kind"] == "RECIRCULATION":
        eligible = membership_id in (ballot.get("_eligible_membership_ids") or [])
    if not eligible:
        fail("ERR_VOTER_NOT_ELIGIBLE", "This seat is not eligible to vote on this ballot.")

    if not ballot_service.in_voting_window(ballot, now()):
        fail("ERR_BALLOT_NOT_IN_VOTING_WINDOW",
             "The logical clock is outside the ballot's half-open voting window.")

    row = insert("votes", {
        "ballot_id": ballot["id"],
        "membership_id": membership_id,
        "position": position,
        "status": "CAST",
        "adjudication_status": "NOT_APPLICABLE",
        "comment_text": comment_text,
        "clause_reference": clause_reference,
        "cast_at": now_iso(),
        "position_change_count": 0,
        "adjudicated_by_participant_id": None,
        "adjudication_rationale": None,
    })

    if position == "NEGATIVE":
        _objection_comment(row, ballot, comment_text, clause_reference)

    seat["missed_ballot_streak"] = 0
    touch(seat)

    ballot_service.recompute_tallies(ballot)
    touch(ballot)
    return envelope.created(public(row))


@bp.get("/sdo/votes")
def list_votes():
    auth.authenticate(auth.READ_ROLES)
    return envelope.list_response(apply_filters(rows("votes"), FILTERS))


@bp.get("/sdo/votes/<vote_id>")
def get_vote(vote_id):
    auth.authenticate(auth.READ_ROLES)
    return envelope.object_response(public(load_path("votes", vote_id)))


@bp.patch("/sdo/votes/<vote_id>")
def revise_vote(vote_id):
    auth.authenticate((auth.COMMITTEE_MEMBER, auth.COMMITTEE_CHAIR))
    vote = load_path("votes", vote_id)
    body = Body(("position", "status", "comment_text"))
    position = body.enum("position", VOTE_POSITION, default=None)
    new_status = body.enum("status", VOTE_STATUS, default=None)
    comment_text = body.string("comment_text", min_len=1, max_len=2000,
                               nullable=True, default=None)

    seat = db.memberships.get(vote["membership_id"])
    auth.require_vote_owner(seat)

    ballot = graph.ballot_of_vote(vote)
    if ballot is None or ballot["status"] != "OPEN":
        fail("ERR_BALLOT_NOT_OPEN", "The ballot is not OPEN.")

    linked = graph.comment_of_vote(vote)
    withdrawing = new_status == "WITHDRAWN"
    if (not withdrawing and position == "NEGATIVE" and vote["position"] != "NEGATIVE"
            and linked is None and not non_empty(comment_text)):
        fail("ERR_NEGATIVE_REQUIRES_COMMENT",
             "Changing a vote to NEGATIVE requires a linked comment or comment_text.")

    if not ballot_service.in_voting_window(ballot, now()):
        fail("ERR_BALLOT_NOT_IN_VOTING_WINDOW",
             "The logical clock is outside the ballot's half-open voting window.")

    if vote["status"] != "CAST":
        bad_request("A withdrawn vote is terminal and cannot be revised.")

    changed = False
    if withdrawing:
        # The linked objection is not deleted; it stays on file.
        vote["status"] = "WITHDRAWN"
        changed = True
    elif position is not None and position != vote["position"]:
        vote["position"] = position
        vote["position_change_count"] = vote["position_change_count"] + 1
        if non_empty(comment_text):
            vote["comment_text"] = comment_text
        if position == "NEGATIVE" and linked is None:
            _objection_comment(vote, ballot, vote["comment_text"], vote["clause_reference"])
        changed = True
    elif non_empty(comment_text) and comment_text != vote["comment_text"]:
        vote["comment_text"] = comment_text
        changed = True

    if changed:
        touch(vote)
        ballot_service.recompute_tallies(ballot)
        touch(ballot)
    return envelope.object_response(public(vote))


@bp.post("/sdo/votes/<vote_id>/adjudicate")
def adjudicate_vote(vote_id):
    auth.authenticate((auth.COMMITTEE_CHAIR, auth.COMMITTEE_MEMBER))
    vote = load_path("votes", vote_id)
    body = Body(("resolution", "adjudication_rationale"))
    resolution = body.enum("resolution", ADJUDICATION_RESOLUTION, required=True)
    rationale = body.string("adjudication_rationale", required=True, min_len=1,
                            max_len=2000)

    ballot = graph.ballot_of_vote(vote)
    draft = graph.draft_of_ballot(ballot) if ballot is not None else None
    work_item = graph.work_item_of_draft(draft) if draft is not None else None
    committee = graph.sponsoring_committee(work_item) if work_item is not None else None
    if committee is None and ballot is not None:
        committee = db.committees.get(ballot["committee_id"])
    seat = db.memberships.get(vote["membership_id"])

    if resolution in ("PERSUASIVE", "NON_PERSUASIVE"):
        auth.require_committee_chair(committee)
    else:
        auth.require_vote_owner(seat)

    if vote["adjudication_status"] != "PENDING" or vote["status"] != "CAST":
        fail("ERR_VOTE_NOT_ADJUDICABLE",
             "Only a cast vote awaiting adjudication may be adjudicated.")

    if resolution in ("PERSUASIVE", "NON_PERSUASIVE"):
        if seat is not None and seat["participant_id"] == auth.caller_id():
            fail("ERR_SELF_ADJUDICATION",
                 "A chair may not rule on their own negative vote.")

    linked = graph.comment_of_vote(vote)
    vote["adjudication_status"] = resolution
    vote["adjudicated_by_participant_id"] = auth.caller_id()
    vote["adjudication_rationale"] = rationale
    if resolution == "PERSUASIVE":
        if vote["position"] == "NEGATIVE":
            vote["position"] = "AFFIRMATIVE"
        if linked is not None:
            linked["status"] = "ACCEPTED"
            touch(linked)
    elif resolution == "NON_PERSUASIVE":
        if linked is not None:
            linked["status"] = "REJECTED"
            touch(linked)
    else:
        if vote["position"] == "NEGATIVE":
            vote["position"] = "ABSTAIN"
    touch(vote)

    if linked is not None and linked.get("public_review_id") is not None:
        from services import reviews as review_service
        review = graph.review_of_comment(linked)
        if review is not None:
            review_service.refresh(review)

    ballot_service.after_adjudication(vote, ballot, draft, work_item)
    return envelope.object_response(public(vote))
