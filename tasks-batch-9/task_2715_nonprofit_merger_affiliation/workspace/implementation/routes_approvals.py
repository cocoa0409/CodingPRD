"""The board approval ledger and its two-signature control — PRD 3.5."""

from flask import Blueprint

import calc
import enums
import services
from auth import authenticate
from db import ORGANIZATIONS, create_row, touch
from errors import fail
from response import ok_row
from validate import body_object, opt_int, req_enum, req_id, req_int, req_str

bp = Blueprint("approvals", __name__)


@bp.post("/board-approvals")
def record_approval():
    actor = authenticate(["BoardSecretary"])
    body = body_object()
    restructuring_id = req_id(body, "restructuring_id")
    expected_version = req_int(body, "expected_restructuring_version")
    approving_party = req_enum(body, "approving_party", enums.PARTIES)
    seats_total = req_int(body, "seats_total", minimum=1, maximum=51)
    recusals = opt_int(body, "recusals", minimum=0, maximum=seats_total, default=0)
    votes_for = req_int(body, "votes_for", minimum=0)
    votes_against = req_int(body, "votes_against", minimum=0)
    abstentions = opt_int(body, "abstentions", minimum=0, default=0)
    disclosures = opt_int(body, "conflict_disclosures_count", minimum=0, default=0)
    recording_secretary_ref = req_str(body, "recording_secretary_ref",
                                      min_len=1, max_len=64)

    deal = services.find_deal(restructuring_id)
    # Ladder rule 13: the acting secretary speaks for the resolved party only.
    party_org_id = services.party_org_for(deal, approving_party)
    services.require_specific_party(actor, party_org_id)
    # Ladder rule 15.
    if expected_version != deal["version"]:
        fail("ERR_STALE_RESTRUCTURING_VERSION",
             "expected_restructuring_version does not match the deal's current version.")
    # Ladder rule 16.
    if deal["status"] not in ("STRUCTURE_SELECTED", "BOARD_APPROVAL"):
        fail("ERR_INVALID_DEAL_STATE",
             "A board resolution cannot be recorded while the deal is %s."
             % deal["status"])

    outcome = calc.board_vote(seats_total, recusals, votes_for, votes_against,
                              abstentions, deal["structure_type"])
    # Ladder rules 36, 37, 38 and 39, in exactly this sequence.
    if disclosures < recusals:
        fail("ERR_CONFLICT_DISCLOSURE_MISSING",
             "Every recused seat must be backed by a disclosed conflict.")
    if outcome["attendance"] > outcome["eligible_seats"]:
        fail("ERR_VOTE_TALLY_EXCEEDS_SEATS",
             "The tally exceeds the number of eligible seats.")
    if outcome["attendance"] < outcome["quorum_required"]:
        fail("ERR_QUORUM_NOT_MET", "Attendance is below the required quorum.")
    if outcome["votes_cast"] <= 0:
        fail("ERR_NO_ELIGIBLE_VOTES",
             "An all-abstain board records no decision.")

    row = create_row("BoardApproval", {
        "restructuring_id": deal["id"],
        "approving_party": approving_party,
        "seats_total": seats_total,
        "recusals": recusals,
        "votes_for": votes_for,
        "votes_against": votes_against,
        "abstentions": abstentions,
        "conflict_disclosures_count": disclosures,
        "eligible_seats": outcome["eligible_seats"],
        "quorum_required": outcome["quorum_required"],
        "votes_cast": outcome["votes_cast"],
        "approval_ratio": float(outcome["approval_ratio"]),
        "required_ratio": float(outcome["required_ratio"]),
        "decision": outcome["decision"],
        "fiduciary_memo_ref": None,
        "recording_secretary_ref": recording_secretary_ref,
        "certifying_secretary_ref": None,
        "pinned_composite_score": None,
        "pinned_assessment_sequence_no": None,
        "allocated_seats": 0,
        "status": "RECORDED" if outcome["decision"] == "APPROVED" else "REJECTED",
        "rescission_reason": None,
    })

    # A re-vote for the same party supersedes that party's prior resolution.
    for prior in services.deal_approvals(deal["id"]):
        if prior["id"] == row["id"]:
            continue
        if (prior["approving_party"] == approving_party
                and prior["status"] in ("RECORDED", "CERTIFIED")):
            prior["status"] = "SUPERSEDED"
            services.return_seats(deal, prior)
            touch(prior)

    if deal["status"] == "STRUCTURE_SELECTED":
        deal["status"] = "BOARD_APPROVAL"
    # The deal's version rises by exactly one for the request either way.
    touch(deal)
    return ok_row(row, 201)


@bp.post("/board-approvals/<approval_id>/certify")
def certify_approval(approval_id):
    actor = authenticate(["BoardSecretary"])
    body = body_object()
    fiduciary_memo_ref = req_str(body, "fiduciary_memo_ref", min_len=1, non_blank=False)
    certifying_secretary_ref = req_str(body, "certifying_secretary_ref",
                                       min_len=1, max_len=64)

    approval = services.find_approval(approval_id)
    deal = services.find_deal(approval["restructuring_id"])
    # Ladder rule 13.
    party_org_id = services.party_org_for(deal, approval["approving_party"])
    services.require_specific_party(actor, party_org_id)
    # Ladder rule 14: the two-signature control runs on the staff references.
    if certifying_secretary_ref == approval["recording_secretary_ref"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The certifying secretary must differ from the recording secretary.")
    # Ladder rule 19.
    if approval["status"] != "RECORDED":
        fail("ERR_INVALID_APPROVAL_STATE",
             "Only a RECORDED resolution can be certified.")
    # Ladder rule 36: re-checked at certification, plus the non-blank memo reference.
    if approval["conflict_disclosures_count"] < approval["recusals"]:
        fail("ERR_CONFLICT_DISCLOSURE_MISSING",
             "Every recused seat must be backed by a disclosed conflict.")
    if fiduciary_memo_ref.strip() == "":
        fail("ERR_CONFLICT_DISCLOSURE_MISSING",
             "fiduciary_memo_ref must be a non-blank reference.")

    approval["status"] = "CERTIFIED"
    approval["fiduciary_memo_ref"] = fiduciary_memo_ref
    approval["certifying_secretary_ref"] = certifying_secretary_ref

    # The evidentiary basis is pinned at the instant of certification.
    assessment = services.latest_assessment(deal["id"], "DILIGENCE_ADJUSTED")
    if assessment is not None:
        approval["pinned_composite_score"] = assessment["composite_score"]
        approval["pinned_assessment_sequence_no"] = assessment["sequence_no"]

    # Seat allocation draws on the governing letter, not on the resolution.
    letter = services.governing_letter(deal["id"])
    seats_due = 0
    if letter is not None:
        split = letter["board_seat_split_initiator"]
        if approval["approving_party"] == "INITIATOR":
            seats_due = split
        else:
            seats_due = deal["combined_board_seats"] - split
    approval["allocated_seats"] = seats_due
    deal["reserved_seat_pool"] -= seats_due
    touch(approval)

    org = ORGANIZATIONS.get(party_org_id)
    if org is not None:
        org["governance_seats"] = seats_due
        touch(org)

    # Both parties certified releases the deal, with the conditional AG bypass.
    certified = set(a["approving_party"] for a in services.deal_approvals(deal["id"])
                    if a["status"] == "CERTIFIED")
    if (deal["status"] == "BOARD_APPROVAL"
            and "INITIATOR" in certified and "TARGET" in certified):
        deal["status"] = "REGULATORY_REVIEW"
        if not deal["ag_review_required"]:
            deal["status"] = "INTEGRATION"
    touch(deal)
    return ok_row(approval)


@bp.post("/board-approvals/<approval_id>/rescind")
def rescind_approval(approval_id):
    actor = authenticate(["BoardSecretary"])
    body = body_object()
    reason = req_str(body, "rescission_reason", min_len=1)

    approval = services.find_approval(approval_id)
    deal = services.find_deal(approval["restructuring_id"])
    # Ladder rule 13.
    party_org_id = services.party_org_for(deal, approval["approving_party"])
    services.require_specific_party(actor, party_org_id)
    # Ladder rule 16.
    if deal["status"] in ("CONSUMMATED", "ABANDONED"):
        fail("ERR_INVALID_DEAL_STATE",
             "A resolution can no longer be rescinded once the deal is %s."
             % deal["status"])
    # Ladder rule 19.
    if approval["status"] != "CERTIFIED":
        fail("ERR_INVALID_APPROVAL_STATE",
             "Only a CERTIFIED resolution can be rescinded.")

    approval["status"] = "RESCINDED"
    approval["rescission_reason"] = reason
    services.return_seats(deal, approval)
    touch(approval)

    org = ORGANIZATIONS.get(party_org_id)
    if org is not None:
        touch(org)

    # The both-parties-certified condition no longer holds.
    if deal["status"] == "REGULATORY_REVIEW":
        deal["status"] = "BOARD_APPROVAL"
    touch(deal)
    return ok_row(approval)
