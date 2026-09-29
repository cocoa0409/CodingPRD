"""Appeals of procedural violations and their remedies (PRD 3.8)."""

from flask import Blueprint

from core import auth, envelope
from core.enums import APPEAL_DECISION, APPEAL_GROUNDS, APPEAL_REMEDY, UPHOLD_REMEDIES
from core.errors import bad_request, fail
from core.store import db, insert, now, now_iso, public, rows, touch
from core.util import iso
from core.validation import Body, apply_filters, load_fk, load_path
from services import gate, graph, ip, schedule

bp = Blueprint("appeals", __name__)

FILTERS = ("work_item_id", "appellant_participant_id", "cited_ballot_id", "status")

STANDING_SEAT_STATES = ("ACTIVE", "SUSPENDED")


def _has_standing(work_item, caller_id):
    if work_item["proposer_participant_id"] == caller_id:
        return True
    committee = graph.sponsoring_committee(work_item)
    if committee is not None:
        for seat in graph.seats_of(committee):
            if (seat["participant_id"] == caller_id
                    and seat["status"] in STANDING_SEAT_STATES):
                return True
    for draft in graph.drafts_of(work_item):
        for comment in db.comments.values():
            if (comment["draft_id"] == draft["id"]
                    and comment["submitter_participant_id"] == caller_id):
                return True
    return False


def _anchor(work_item, ballot):
    """The instant the 30-day filing window counts from."""
    if ballot is not None:
        return ballot.get("_closed_at")
    return work_item.get("_published_at")


@bp.post("/sdo/appeals")
def file_appeal():
    auth.authenticate((auth.PROPOSER, auth.COMMITTEE_MEMBER, auth.COMMITTEE_CHAIR,
                       auth.PUBLIC_COMMENTER))
    body = Body(("work_item_id", "appellant_participant_id", "cited_ballot_id",
                 "grounds", "statement"))
    work_item_id = body.id_ref("work_item_id", required=True)
    appellant_id = body.id_ref("appellant_participant_id", required=True)
    cited_ballot_id = body.id_ref("cited_ballot_id", nullable=True, default=None)
    grounds = body.enum("grounds", APPEAL_GROUNDS, required=True)
    statement = body.string("statement", required=True, min_len=1, max_len=2000)

    work_item = load_fk("work_items", work_item_id, optional=False)
    load_fk("participants", appellant_id, optional=False)
    cited_ballot = load_fk("ballots", cited_ballot_id)
    auth.require_actor_identity(appellant_id)

    # Standing at precedence 97 is decided before timeliness at 117.
    if not _has_standing(work_item, auth.caller_id()):
        fail("ERR_APPELLANT_NOT_INTERESTED_PARTY",
             "The appellant is not an interested party to this work item.")

    anchor = _anchor(work_item, cited_ballot)
    if anchor is None:
        fail("ERR_APPEAL_ANCHOR_MISSING",
             "There is no closed ballot or publication instant to count from.")

    deadline = schedule.appeal_deadline(anchor)
    if now() > deadline:
        fail("ERR_APPEAL_UNTIMELY",
             "The 30-day appeal window closed at %s." % iso(deadline))

    row = insert("appeals", {
        "work_item_id": work_item["id"],
        "appellant_participant_id": appellant_id,
        "cited_ballot_id": cited_ballot["id"] if cited_ballot is not None else None,
        "grounds": grounds,
        "statement": statement,
        "status": "FILED",
        "remedy": "NONE",
        "filed_at": now_iso(),
        "filing_deadline_at": iso(deadline),
        "decided_at": None,
        "decision_rationale": None,
    })

    # Filing alone is a stop-work order: the gate shuts and the work item versions.
    gate.recompute(work_item, bump=True)
    return envelope.created(public(row))


@bp.get("/sdo/appeals")
def list_appeals():
    auth.authenticate(auth.READ_ROLES)
    return envelope.list_response(apply_filters(rows("appeals"), FILTERS))


@bp.get("/sdo/appeals/<appeal_id>")
def get_appeal(appeal_id):
    auth.authenticate(auth.READ_ROLES)
    return envelope.object_response(public(load_path("appeals", appeal_id)))


def _release_holds(work_item, cited_ballot):
    """A denial releases every APPEAL_PENDING hold back to NONE."""
    candidates = []
    seen = set()
    if cited_ballot is not None:
        candidates.append(cited_ballot)
        seen.add(cited_ballot["id"])
    if work_item is not None:
        for ballot in graph.ballots_of_work_item(work_item):
            if ballot["id"] not in seen:
                candidates.append(ballot)
                seen.add(ballot["id"])
    for ballot in candidates:
        if ballot["hold_reason"] == "APPEAL_PENDING":
            ballot["hold_reason"] = "NONE"
            touch(ballot)


def _target_draft(work_item, cited_ballot):
    if cited_ballot is not None:
        draft = db.drafts.get(cited_ballot["draft_id"])
        if draft is not None:
            return draft
    return graph.latest_draft_of(work_item) if work_item is not None else None


@bp.post("/sdo/appeals/<appeal_id>/decide")
def decide_appeal(appeal_id):
    auth.authenticate((auth.APPEALS_BOARD,))
    appeal = load_path("appeals", appeal_id)
    body = Body(("decision", "decision_rationale", "remedy"))
    decision = body.enum("decision", APPEAL_DECISION, required=True)
    rationale = body.string("decision_rationale", required=True, min_len=1, max_len=2000)
    remedy = body.enum("remedy", APPEAL_REMEDY, default=None)
    if decision == "UPHOLD" and remedy not in UPHOLD_REMEDIES:
        bad_request("An upholding requires a remedy other than NONE.")

    work_item = db.work_items.get(appeal["work_item_id"])
    cited_ballot = db.ballots.get(appeal["cited_ballot_id"]) \
        if appeal["cited_ballot_id"] else None

    if decision == "ACCEPT_FOR_REVIEW":
        if appeal["status"] != "FILED":
            fail("ERR_INVALID_APPEAL_STATE",
                 "Only a FILED appeal may be accepted for review.")
    elif decision == "UPHOLD":
        if appeal["status"] != "ACCEPTED_FOR_REVIEW":
            fail("ERR_INVALID_APPEAL_STATE",
                 "Only an appeal ACCEPTED_FOR_REVIEW may be upheld.")
    else:
        if appeal["status"] not in ("FILED", "ACCEPTED_FOR_REVIEW"):
            fail("ERR_INVALID_APPEAL_STATE", "The appeal has already been decided.")

    if decision == "ACCEPT_FOR_REVIEW":
        appeal["status"] = "ACCEPTED_FOR_REVIEW"
        appeal["decision_rationale"] = rationale
        touch(appeal)
        if cited_ballot is not None and cited_ballot["status"] == "OPEN":
            cited_ballot["hold_reason"] = "APPEAL_PENDING"
            touch(cited_ballot)
        if work_item is not None:
            gate.recompute(work_item)
        return envelope.object_response(public(appeal))

    if decision == "DENY":
        appeal["status"] = "DENIED"
        appeal["remedy"] = "NONE"
        appeal["decision_rationale"] = rationale
        appeal["decided_at"] = now_iso()
        touch(appeal)
        _release_holds(work_item, cited_ballot)
        if work_item is not None:
            gate.recompute(work_item, bump=True)
        return envelope.object_response(public(appeal))

    # UPHOLD: a four-hop cascade.
    appeal["status"] = "UPHELD"
    appeal["remedy"] = remedy
    appeal["decision_rationale"] = rationale
    appeal["decided_at"] = now_iso()
    touch(appeal)

    vacated = False
    if remedy == "VACATE_BALLOT" and cited_ballot is not None:
        if cited_ballot["status"] in ("EVALUATED", "OPEN"):
            # Tallies and percentages are preserved exactly as the historical
            # record; an OPEN ballot freezes nothing at all.
            cited_ballot["status"] = "VACATED"
            cited_ballot["hold_reason"] = "NONE"
            touch(cited_ballot)
            vacated = True

    if remedy == "SUSPEND_STANDARD":
        if work_item is not None:
            if work_item["progress_status"] in ("PUBLISHED", "REAFFIRMED"):
                work_item["progress_status"] = "SUSPENDED"
            touch(work_item)
            gate.recompute(work_item)
        return envelope.object_response(public(appeal))

    if vacated or remedy == "REMAND_TO_COMMITTEE":
        draft = _target_draft(work_item, cited_ballot)
        if draft is not None:
            if draft["status"] == "APPROVED":
                draft["status"] = "DRAFTING"
            elif draft["status"] == "CONSENSUS_BALLOT":
                draft["status"] = "PUBLIC_REVIEW_CLOSED"
            if cited_ballot is not None:
                # Every negative cast on the ballot carries forward, adjudicated
                # or not, and raises the approval bar by 5.0 points next round.
                draft["carryover_unresolved_negative_count"] = \
                    cited_ballot["negative_count"]
            touch(draft)
        if work_item is not None:
            reopened = work_item["progress_status"] == "CONSENSUS_APPROVED"
            if reopened:
                work_item["progress_status"] = "IN_DEVELOPMENT"
            touch(work_item)
            if reopened:
                # Reopening development reopens the call for patents, so the
                # clearance derivation runs again now that progress_status reads
                # IN_DEVELOPMENT: a work item with no disclosures at all moves
                # back from IP_CLEARED to IP_PENDING (PRD 3.7).
                ip.recompute(work_item)
            gate.recompute(work_item)
    return envelope.object_response(public(appeal))
