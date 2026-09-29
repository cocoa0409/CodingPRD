"""Ballots: opening a round and closing it (PRD 3.3, 3.5)."""

from flask import Blueprint

from core import auth, envelope
from core.enums import BALLOT_KIND
from core.errors import fail
from core.store import insert, now, public, rows, touch
from core.validation import Body, apply_filters, load_fk, load_path, no_body
from services import balance, ballots as ballot_service, gate, graph

bp = Blueprint("ballots", __name__)

FILTERS = ("draft_id", "committee_id", "predecessor_ballot_id", "status",
           "consensus_result")

DRAFT_TRANSITION = {
    "DRAFTING": "SUBCOMMITTEE_BALLOT",
    "PUBLIC_REVIEW_CLOSED": "CONSENSUS_BALLOT",
    "APPROVED": "APPROVED",
}


@bp.post("/sdo/ballots")
def open_ballot():
    auth.authenticate((auth.COMMITTEE_CHAIR,))
    body = Body(("draft_id", "committee_id", "ballot_kind", "opens_at", "closes_at",
                 "predecessor_ballot_id"))
    draft_id = body.id_ref("draft_id", required=True)
    committee_id = body.id_ref("committee_id", required=True)
    ballot_kind = body.enum("ballot_kind", BALLOT_KIND, required=True)
    opens_at = body.instant("opens_at", required=True)
    closes_at = body.instant("closes_at", required=True)
    predecessor_ballot_id = body.id_ref("predecessor_ballot_id", nullable=True,
                                        default=None)

    draft = load_fk("drafts", draft_id, optional=False)
    committee = load_fk("committees", committee_id, optional=False)
    predecessor = load_fk("ballots", predecessor_ballot_id)

    auth.require_committee_chair(committee)

    allowed_states = ["DRAFTING", "PUBLIC_REVIEW_CLOSED"]
    if ballot_kind == "REAFFIRMATION":
        allowed_states.append("APPROVED")
    if draft["status"] not in allowed_states:
        fail("ERR_INVALID_DRAFT_STATE",
             "A draft in %s cannot open this ballot." % draft["status"])

    work_item = graph.work_item_of_draft(draft)
    if ballot_kind == "REAFFIRMATION":
        if work_item is None or work_item["progress_status"] != "UNDER_PERIODIC_REVIEW":
            fail("ERR_INVALID_WORK_ITEM_STATE",
                 "A reaffirmation ballot requires the work item to be UNDER_PERIODIC_REVIEW.")

    if committee["status"] != "ACTIVE":
        fail("ERR_COMMITTEE_NOT_ACTIVE", "The committee is not ACTIVE.")

    if draft["status"] == "PUBLIC_REVIEW_CLOSED":
        if not ballot_service.latest_review_approved(draft):
            fail("ERR_PUBLIC_REVIEW_NOT_APPROVED",
                 "The draft's most recent public review is not DISPOSITION_APPROVED.")

    if committee["balance_status"] != "BALANCED":
        fail("ERR_COMMITTEE_NOT_BALANCED",
             "The committee's voting-basis balance is not BALANCED.")

    occupants = ballot_service.occupied_slots(committee, opens_at, closes_at)
    if len(occupants) >= committee["max_concurrent_ballots"]:
        fail("ERR_BALLOT_CAPACITY_EXCEEDED",
             "The committee's concurrent ballot capacity is exhausted for this window.")

    effective_kind, derived_predecessor = ballot_service.derive_effective_kind(
        draft, ballot_kind, predecessor)

    minimum_days = ballot_service.MIN_WINDOW_DAYS[effective_kind]
    if opens_at >= closes_at or ballot_service.day_span_days(opens_at, closes_at) < minimum_days:
        fail("ERR_BALLOT_WINDOW_TOO_SHORT",
             "A %s ballot needs a window of at least %d whole days."
             % (effective_kind, minimum_days))

    seats = ballot_service.eligible_seats(committee, effective_kind, derived_predecessor)
    required_return, required_approval = ballot_service.thresholds(effective_kind, draft)

    row = insert("ballots", {
        "draft_id": draft["id"],
        "committee_id": committee["id"],
        "predecessor_ballot_id": predecessor["id"] if predecessor is not None else None,
        "ballot_kind": ballot_kind,
        "effective_ballot_kind": effective_kind,
        "opens_at": body.raw("opens_at"),
        "closes_at": body.raw("closes_at"),
        "closed_at": None,
        "status": "OPEN",
        "hold_reason": "NONE",
        "eligible_voter_count": len(seats),
        "affirmative_count": 0,
        "negative_count": 0,
        "abstain_count": 0,
        "returned_count": 0,
        "not_returned_count": len(seats),
        "return_rate_pct": 0.0,
        "required_return_rate_pct": required_return,
        "required_approval_pct": required_approval,
        "provisional_approval_pct": None,
        "final_approval_pct": None,
        "pending_negative_count": 0,
        "consensus_result": "PENDING",
        "_opens_at": opens_at,
        "_closes_at": closes_at,
        "_closed_at": None,
        "_eligible_membership_ids": [seat["id"] for seat in seats],
    })

    draft["status"] = DRAFT_TRANSITION.get(draft["status"], draft["status"])
    ballot_service.refresh_ballot_round_count(draft)
    touch(draft)

    balance.refresh_open_ballot_count(committee)
    touch(committee)

    if work_item is not None:
        gate.recompute(work_item)
        touch(work_item)
    return envelope.created(public(row))


@bp.get("/sdo/ballots")
def list_ballots():
    auth.authenticate(auth.READ_ROLES)
    return envelope.list_response(apply_filters(rows("ballots"), FILTERS))


@bp.get("/sdo/ballots/<ballot_id>")
def get_ballot(ballot_id):
    auth.authenticate(auth.READ_ROLES)
    return envelope.object_response(public(load_path("ballots", ballot_id)))


@bp.post("/sdo/ballots/<ballot_id>/close")
def close_ballot(ballot_id):
    auth.authenticate((auth.COMMITTEE_CHAIR, auth.STANDARDS_STAFF))
    ballot = load_path("ballots", ballot_id)
    no_body()

    if ballot["status"] != "OPEN":
        fail("ERR_BALLOT_NOT_OPEN", "Only an OPEN ballot may be closed.")

    if ballot["hold_reason"] != "NONE":
        fail("ERR_COMMITTEE_NOT_BALANCED",
             "The ballot carries a procedural hold (%s) and cannot be closed."
             % ballot["hold_reason"])

    ended = now() >= ballot["_closes_at"]
    fully_returned = ballot["returned_count"] == ballot["eligible_voter_count"]
    if not ended and not fully_returned:
        fail("ERR_BALLOT_NOT_ENDED",
             "The voting window has not ended and not every seat has returned.")

    ballot_service.close(ballot)
    return envelope.object_response(public(ballot))
