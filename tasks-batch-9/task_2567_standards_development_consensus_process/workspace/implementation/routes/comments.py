"""Comments and the comment disposition record (PRD 3.6)."""

from flask import Blueprint

from core import auth, envelope
from core.enums import COMMENT_TYPE, DISPOSING_ACTIONS, DISPOSITION_ACTION
from core.errors import bad_request, fail
from core.store import insert, public, rows, touch
from core.validation import Body, apply_filters, load_fk, load_path
from services import graph, reviews as review_service

bp = Blueprint("comments", __name__)

FILTERS = ("draft_id", "ballot_id", "public_review_id", "source_vote_id",
           "submitter_participant_id", "status")

SUBSTANTIVE_TYPES = ("GENERAL", "TECHNICAL")
CLIENT_SOURCE_TYPES = ("PUBLIC_REVIEW", "COMMITTEE")


@bp.post("/sdo/comments")
def create_comment():
    auth.authenticate((auth.PUBLIC_COMMENTER, auth.COMMITTEE_MEMBER,
                       auth.COMMITTEE_CHAIR, auth.PROPOSER))
    body = Body(("draft_id", "public_review_id", "submitter_participant_id",
                 "source_type", "comment_type", "clause_reference", "comment_text"))
    # BALLOT_NEGATIVE is the server's own record of a negative vote and is refused
    # as client input.
    source_type = body.enum("source_type", CLIENT_SOURCE_TYPES, required=True)
    comment_type = body.enum("comment_type", COMMENT_TYPE, required=True)
    comment_text = body.string("comment_text", required=True, min_len=1, max_len=2000)
    clause_reference = body.string("clause_reference", required=True, min_len=1,
                                   max_len=40)
    submitter_id = body.id_ref("submitter_participant_id", required=True)
    draft_id = body.id_ref("draft_id", required=(source_type == "COMMITTEE"))
    public_review_id = body.id_ref("public_review_id",
                                   required=(source_type == "PUBLIC_REVIEW"))

    draft = load_fk("drafts", draft_id)
    review = load_fk("public_reviews", public_review_id)
    load_fk("participants", submitter_id, optional=False)
    auth.require_actor_identity(submitter_id)

    if source_type != "PUBLIC_REVIEW":
        # Only a PUBLIC_REVIEW comment joins a review's disposition ledger.
        review = None

    if source_type == "PUBLIC_REVIEW":
        if review["status"] != "OPEN":
            fail("ERR_INVALID_PUBLIC_REVIEW_STATE",
                 "Comments are only accepted while the review is OPEN.")
        draft_id = review["draft_id"]
    else:
        draft_id = draft["id"]

    row = insert("comments", {
        "draft_id": draft_id,
        "ballot_id": None,
        "public_review_id": review["id"] if review is not None else None,
        "source_vote_id": None,
        "submitter_participant_id": submitter_id,
        "source_type": source_type,
        "comment_type": comment_type,
        "clause_reference": clause_reference,
        "comment_text": comment_text,
        "status": "OPEN",
        "is_substantive": comment_type in SUBSTANTIVE_TYPES,
        "disposition_rationale": None,
    })

    if review is not None:
        review_service.refresh(review)
    return envelope.created(public(row))


@bp.get("/sdo/comments")
def list_comments():
    auth.authenticate(auth.READ_ROLES)
    return envelope.list_response(apply_filters(rows("comments"), FILTERS))


@bp.get("/sdo/comments/<comment_id>")
def get_comment(comment_id):
    auth.authenticate(auth.READ_ROLES)
    return envelope.object_response(public(load_path("comments", comment_id)))


@bp.post("/sdo/comments/<comment_id>/disposition")
def disposition_comment(comment_id):
    auth.authenticate((auth.COMMITTEE_CHAIR,))
    comment = load_path("comments", comment_id)
    body = Body(("disposition", "disposition_rationale"))
    disposition = body.enum("disposition", DISPOSITION_ACTION, required=True)
    rationale = body.string("disposition_rationale",
                            required=(disposition in DISPOSING_ACTIONS),
                            min_len=1, max_len=2000, nullable=True, default=None)
    if disposition in DISPOSING_ACTIONS and (rationale is None or rationale.strip() == ""):
        bad_request("A disposition requires a written disposition_rationale.")

    draft = graph.draft_of_comment(comment)
    work_item = graph.work_item_of_draft(draft) if draft is not None else None
    committee = graph.sponsoring_committee(work_item)
    auth.require_committee_chair(committee)

    review = graph.review_of_comment(comment)

    if disposition == "REOPENED":
        if review is not None and review["status"] == "DISPOSITION_APPROVED":
            fail("ERR_INVALID_PUBLIC_REVIEW_STATE",
                 "An approved disposition record can no longer be reopened.")
        if comment["status"] not in DISPOSING_ACTIONS:
            fail("ERR_INVALID_COMMENT_STATE",
                 "Only a dispositioned comment may be reopened.")
        comment["status"] = "OPEN"
        comment["disposition_rationale"] = None
    else:
        if comment["status"] != "OPEN":
            fail("ERR_INVALID_COMMENT_STATE",
                 "Only an OPEN comment may be dispositioned.")
        comment["status"] = disposition
        comment["disposition_rationale"] = rationale
    touch(comment)

    if review is not None:
        # REOPENED is the exact compensation of the three disposing outcomes:
        # recomputing from the comment rows leaves no counter drift.
        review_service.refresh(review)
    return envelope.object_response(public(comment))
