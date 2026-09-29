"""Technical committees, activation and seat appointment (PRD 3.1)."""

from flask import Blueprint

from core import auth, envelope
from core.errors import fail
from core.store import insert, now, now_iso, public, rows, touch
from core.validation import Body, apply_filters, load_fk, load_path, no_body
from services import balance, gate, graph

bp = Blueprint("committees", __name__)

FILTERS = ("chair_participant_id", "status", "balance_status")
BLOCKING_SEAT_STATES = ("ACTIVE", "SUSPENDED")


@bp.post("/sdo/committees")
def create_committee():
    auth.authenticate((auth.STANDARDS_STAFF,))
    body = Body(("designation", "scope_text", "chair_participant_id",
                 "max_concurrent_ballots"))
    designation = body.string("designation", required=True, min_len=1, max_len=32)
    scope_text = body.string("scope_text", required=True, min_len=1, max_len=600)
    chair_id = body.id_ref("chair_participant_id", required=True)
    max_concurrent = body.integer("max_concurrent_ballots", minimum=1, default=2)
    load_fk("participants", chair_id, optional=False)

    row = insert("committees", {
        "designation": designation,
        "scope_text": scope_text,
        "chair_participant_id": chair_id,
        "max_concurrent_ballots": max_concurrent,
        "status": "FORMING",
        "balance_status": "UNBALANCED",
        "active_member_count": 0,
        "dominance_pct": 0.0,
        "distinct_category_count": 0,
        "category_counts": {},
        "roster_balance_status": "UNBALANCED",
        "roster_member_count": 0,
        "roster_dominance_pct": 0.0,
        "open_ballot_count": 0,
    })
    # The balance arithmetic runs on the empty roster it is born with.
    balance.recompute(row)
    return envelope.created(public(row))


@bp.get("/sdo/committees")
def list_committees():
    auth.authenticate(auth.READ_ROLES)
    return envelope.list_response(apply_filters(rows("committees"), FILTERS))


@bp.get("/sdo/committees/<committee_id>")
def get_committee(committee_id):
    auth.authenticate(auth.READ_ROLES)
    return envelope.object_response(public(load_path("committees", committee_id)))


@bp.post("/sdo/committees/<committee_id>/activate")
def activate_committee(committee_id):
    auth.authenticate((auth.STANDARDS_STAFF,))
    committee = load_path("committees", committee_id)
    no_body()

    # Precedence 82, then the chair test, then the freshly recomputed verdict.
    if committee["status"] not in ("FORMING", "SUSPENDED"):
        fail("ERR_INVALID_COMMITTEE_STATE",
             "Only a FORMING or SUSPENDED committee may be activated.")

    chair_seat = None
    for seat in graph.seats_of(committee):
        if (seat["participant_id"] == committee["chair_participant_id"]
                and seat["status"] == "ACTIVE" and seat["voting_rights"] is True):
            chair_seat = seat
            break
    if chair_seat is None:
        fail("ERR_CHAIR_NOT_MEMBER",
             "The nominated chair does not hold an active voting seat on this committee.")

    verdict = balance.voting_basis(committee)["verdict"]
    if verdict != "BALANCED":
        fail("ERR_COMMITTEE_NOT_BALANCED",
             "The committee's voting-basis balance is %s, not BALANCED." % verdict)

    came_from_suspended = committee["status"] == "SUSPENDED"
    balance.recompute(committee)
    committee["status"] = "ACTIVE"
    touch(committee)

    if came_from_suspended:
        for ballot in graph.ballots_of_committee(committee):
            if ballot["hold_reason"] == "COMMITTEE_UNBALANCED":
                ballot["hold_reason"] = "NONE"
                touch(ballot)
    gate.recompute_for_committee(committee)
    return envelope.object_response(public(committee))


@bp.post("/sdo/committees/<committee_id>/memberships")
def appoint_membership(committee_id):
    auth.authenticate((auth.STANDARDS_STAFF,))
    committee = load_path("committees", committee_id)
    body = Body(("participant_id", "voting_rights"))
    participant_id = body.id_ref("participant_id", required=True)
    voting_rights = body.boolean("voting_rights", default=True)
    participant = load_fk("participants", participant_id, optional=False)

    seats = graph.seats_of(committee)
    for seat in seats:
        if (seat["participant_id"] == participant_id
                and seat["status"] in BLOCKING_SEAT_STATES):
            fail("ERR_DUPLICATE_MEMBERSHIP",
                 "This participant already holds a live seat on the committee.")

    affiliation = participant.get("employer_affiliation_code")
    if affiliation is not None:
        for seat in seats:
            if (seat["status"] in BLOCKING_SEAT_STATES
                    and seat.get("employer_affiliation_code") == affiliation):
                fail("ERR_AFFILIATION_ALREADY_REPRESENTED",
                     "This employer affiliation already holds a live seat.")

    row = insert("memberships", {
        "committee_id": committee["id"],
        "participant_id": participant_id,
        "interest_category": participant["interest_category"],
        "employer_affiliation_code": affiliation,
        "voting_rights": voting_rights,
        "status": "ACTIVE",
        "appointed_at": now_iso(),
        "missed_ballot_streak": 0,
        "_appointed_at": now(),
    })
    balance.recompute(committee)
    touch(committee)
    return envelope.created(public(row))
