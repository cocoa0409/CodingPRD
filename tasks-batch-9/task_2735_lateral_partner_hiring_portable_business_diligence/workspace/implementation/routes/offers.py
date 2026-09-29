"""Compensation offers, committee voting and the hire (PRD 3.6)."""

from datetime import timedelta

import calculations as calc
import listing
import lookups as lk
import middleware as mw
import services as svc
from db import db, new_row, pub, set_fields, sorted_rows
from errors import ApiError
from flask import Blueprint
from response import object_response

bp = Blueprint("offers", __name__, url_prefix="/lateral-hiring")

READ_OFFER = ("SystemAdmin", "RecruitingCoordinator", "PracticeGroupLeader",
              "CommitteeMember", "CommitteeChair", "Candidate")
LIST_OFFER = ("SystemAdmin", "RecruitingCoordinator", "PracticeGroupLeader",
              "CommitteeMember", "CommitteeChair")
VOTE_ROLES = ("SystemAdmin", "CommitteeMember", "CommitteeChair")


def _assessment_currency(assessment):
    """Ladder priority 16."""
    if assessment["status"] == "CURRENT":
        return
    if assessment["status"] == "STALE":
        raise ApiError("ERR_ASSESSMENT_STALE")
    raise ApiError("ERR_ASSESSMENT_INVALID_STATE")


def _group_of_candidate(candidate):
    return db.practice_groups.get(candidate["target_practice_group_id"])


@bp.post("/candidates/<candidate_id>/offers")
def create_offer(candidate_id):
    user_id, _role = mw.authenticate(("CommitteeChair",))
    candidate = lk.get_candidate(candidate_id)
    data = mw.body()
    assessment = None
    if isinstance(data.get("portability_assessment_id"), str):
        assessment = lk.get_assessment(data["portability_assessment_id"])

    mw.v_str(data, "portability_assessment_id", 1, None)
    guaranteed = mw.v_num(data, "guaranteed_comp_usd", minimum=0, exclusive_min=True)
    signing_bonus = mw.v_num(data, "signing_bonus_usd", minimum=0)
    expected_version = mw.v_int(data, "expected_candidate_version")

    if expected_version != candidate["version"]:
        raise ApiError("ERR_STALE_CANDIDATE_VERSION")
    if candidate["pipeline_status"] != "DILIGENCE":
        raise ApiError("ERR_CANDIDATE_INVALID_STATE")
    questionnaire = db.questionnaires.get(assessment["questionnaire_id"])
    if questionnaire is None or questionnaire["candidate_id"] != candidate["id"]:
        raise ApiError("ERR_ASSESSMENT_CANDIDATE_MISMATCH")
    _assessment_currency(assessment)

    group = _group_of_candidate(candidate)
    row = new_row({
        "candidate_id": candidate["id"],
        "portability_assessment_id": assessment["id"],
        "created_by_user_id": user_id,
        "guaranteed_comp_usd": guaranteed,
        "signing_bonus_usd": signing_bonus,
        "round_number": 1,
        "status": "DRAFTED",
        "eligible_voter_count": None,
        "adjusted_portable_total_snapshot_usd":
            assessment["adjusted_portable_total_usd"],
        "expected_contribution_usd": calc.ZERO,
        "total_first_year_comp_usd": calc.ZERO,
        "search_fee_amount_usd": calc.ZERO,
        "integration_cost_total_usd": calc.ZERO,
        "net_first_year_economics_usd": calc.ZERO,
        "guarantee_true_up_amount_usd": calc.ZERO,
        "votes_cast_total": 0,
        "active_vote_count": 0,
        "voided_vote_count": 0,
        "accepted_at": None,
    })
    row.update(svc.offer_economics(row, candidate, group))
    db.offers[row["id"]] = row
    set_fields(candidate, open_offer_id=row["id"])
    return object_response(pub(row), 201)


@bp.get("/offers/<offer_id>")
def read_offer(offer_id):
    mw.authenticate(READ_OFFER)
    return object_response(pub(lk.get_offer(offer_id)))


@bp.get("/offers")
def list_offers():
    mw.authenticate(LIST_OFFER)
    rows = list(db.offers.values())
    rows = listing.eq_filter(rows, "candidate_id")
    rows = listing.eq_filter(rows, "portability_assessment_id")
    rows = listing.eq_filter(rows, "status")
    return listing.paged(rows)


@bp.patch("/offers/<offer_id>")
def redraft_offer(offer_id):
    mw.authenticate(("CommitteeChair",))
    offer = lk.get_offer(offer_id)
    data = mw.body()
    guaranteed = mw.v_num(data, "guaranteed_comp_usd", minimum=0, exclusive_min=True)
    signing_bonus = mw.v_num(data, "signing_bonus_usd", minimum=0)
    if offer["status"] != "COUNTER_REQUESTED":
        raise ApiError("ERR_OFFER_INVALID_STATE")

    candidate = db.candidates.get(offer["candidate_id"])
    group = _group_of_candidate(candidate)
    probe = dict(offer)
    probe["guaranteed_comp_usd"] = guaranteed
    probe["signing_bonus_usd"] = signing_bonus
    economics = svc.offer_economics(probe, candidate, group)
    set_fields(offer, status="DRAFTED", guaranteed_comp_usd=guaranteed,
               signing_bonus_usd=signing_bonus, **economics)
    return object_response(pub(offer))


@bp.post("/offers/<offer_id>/submit")
def submit_offer(offer_id):
    mw.authenticate(("CommitteeChair",))
    offer = lk.get_offer(offer_id)
    data = mw.body()
    eligible_voter_count = mw.v_int(data, "eligible_voter_count", minimum=0)

    if offer["status"] != "DRAFTED":
        raise ApiError("ERR_OFFER_INVALID_STATE")
    candidate = db.candidates.get(offer["candidate_id"])
    if candidate is None or candidate["clearance_status"] != "CLEARED":
        raise ApiError("ERR_CLEARANCE_INCOMPLETE")
    assessment = db.assessments.get(offer["portability_assessment_id"])
    if assessment is not None:
        _assessment_currency(assessment)
    if eligible_voter_count < calc.MIN_COMMITTEE_SIZE:
        raise ApiError("ERR_COMMITTEE_TOO_SMALL")
    group = _group_of_candidate(candidate)
    if group is None or group["status"] != "OPEN":
        raise ApiError("ERR_PRACTICE_GROUP_FROZEN")
    if offer["guaranteed_comp_usd"] > group["available_guarantee_budget_usd"]:
        raise ApiError("ERR_GUARANTEE_BUDGET_EXCEEDED")

    set_fields(offer, status="COMMITTEE_REVIEW",
               eligible_voter_count=eligible_voter_count)
    svc.sync_group_ledger(group)
    return object_response(pub(offer))


@bp.post("/offers/<offer_id>/finalize")
def finalize_offer(offer_id):
    user_id, _role = mw.authenticate(("CommitteeChair",))
    offer = lk.get_offer(offer_id)
    if offer["status"] != "COMMITTEE_REVIEW":
        raise ApiError("ERR_OFFER_INVALID_STATE")
    if user_id == offer["created_by_user_id"]:
        raise ApiError("ERR_OFFER_CREATOR_CANNOT_FINALIZE")

    live = [v for v in lk.votes_of_offer(offer["id"])
            if v["status"] == "ACTIVE" and v["round_number"] == offer["round_number"]]
    approve = len([v for v in live if v["decision"] == "APPROVE"])
    reject = len([v for v in live if v["decision"] == "REJECT"])
    abstain = len([v for v in live if v["decision"] == "ABSTAIN"])
    cast = approve + reject + abstain
    if cast < calc.quorum_minimum(offer["eligible_voter_count"] or 0):
        raise ApiError("ERR_QUORUM_NOT_MET")

    candidate = db.candidates.get(offer["candidate_id"])
    if calc.approval_met(approve, reject):
        set_fields(offer, status="APPROVED")
        if candidate is not None:
            set_fields(candidate, pipeline_status="OFFER_OUT",
                       open_offer_id=offer["id"])
    else:
        set_fields(offer, status="REJECTED")
        if candidate is not None:
            set_fields(candidate, pipeline_status="DECLINED", open_offer_id=None)
    svc.sync_group_for_offer(offer)
    return object_response(pub(offer))


@bp.post("/offers/<offer_id>/counter")
def counter_offer(offer_id):
    mw.authenticate(("CommitteeChair",))
    offer = lk.get_offer(offer_id)
    data = mw.body()
    mw.v_str(data, "counter_note", 1, 500)
    if offer["status"] not in ("COMMITTEE_REVIEW", "REPRICE_REQUIRED"):
        raise ApiError("ERR_OFFER_INVALID_STATE")
    if offer["round_number"] >= calc.MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_NEGOTIATION_ROUND_LIMIT_EXCEEDED")

    for vote in sorted_rows(lk.votes_of_offer(offer["id"])):
        if vote["status"] == "ACTIVE":
            set_fields(vote, status="VOIDED")
    set_fields(offer, status="COUNTER_REQUESTED",
               round_number=offer["round_number"] + 1,
               eligible_voter_count=None)
    svc.sync_vote_counters(offer)
    svc.sync_group_for_offer(offer)
    return object_response(pub(offer))


@bp.post("/offers/<offer_id>/accept")
def accept_offer(offer_id):
    user_id, _role = mw.authenticate(("Candidate",))
    offer = lk.get_offer(offer_id)
    if user_id != offer["candidate_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if offer["status"] != "APPROVED":
        raise ApiError("ERR_OFFER_INVALID_STATE")
    candidate = db.candidates.get(offer["candidate_id"])
    if candidate is None or candidate["clearance_status"] != "CLEARED":
        raise ApiError("ERR_CLEARANCE_INCOMPLETE")

    moment = db.clock
    set_fields(offer, status="ACCEPTED", accepted_at=moment)
    svc.sync_group_for_offer(offer)

    # Hop 2 -- the hire itself.
    earliest = moment + timedelta(days=candidate["notice_period_days"])
    set_fields(candidate, pipeline_status="HIRED", resignation_date=moment,
               hire_date=moment, earliest_start_date=earliest,
               open_offer_id=offer["id"])

    # Hop 3 -- the placement fee crystallises on the sourcing engagement.
    engagement = db.engagements.get(candidate["sourcing_engagement_id"])
    if engagement is not None:
        basis, amount = svc.search_fee_liability(
            engagement, offer["total_first_year_comp_usd"],
            offer["guaranteed_comp_usd"], candidate["hire_date"])
        set_fields(engagement, fee_basis=basis, fee_amount_usd=amount,
                   fee_status="FEE_DUE")
    return object_response(pub(offer))


# --------------------------------------------------------------------- votes

@bp.post("/offers/<offer_id>/votes")
def cast_vote(offer_id):
    user_id, _role = mw.authenticate(("CommitteeMember", "CommitteeChair"))
    offer = lk.get_offer(offer_id)
    data = mw.body()
    decision = mw.v_enum(data, "decision", ("APPROVE", "REJECT", "ABSTAIN"))
    round_number = mw.v_int(data, "round_number", minimum=1)
    rationale = mw.v_str(data, "rationale", 1, 500, required=False)

    if offer["status"] != "COMMITTEE_REVIEW":
        raise ApiError("ERR_OFFER_INVALID_STATE")
    candidate = db.candidates.get(offer["candidate_id"])
    if candidate is not None and user_id == candidate["sponsor_user_id"]:
        raise ApiError("ERR_SPONSOR_CANNOT_VOTE")
    if round_number != offer["round_number"]:
        raise ApiError("ERR_VOTE_ROUND_MISMATCH")
    for vote in lk.votes_of_offer(offer["id"]):
        if vote["voter_user_id"] == user_id and vote["status"] == "ACTIVE":
            raise ApiError("ERR_DUPLICATE_VOTE")
    if offer["eligible_voter_count"] is not None and \
            offer["active_vote_count"] >= offer["eligible_voter_count"]:
        raise ApiError("ERR_VOTE_ROLL_FULL")

    row = new_row({
        "offer_id": offer["id"],
        "voter_user_id": user_id,
        "decision": decision,
        "round_number": round_number,
        "rationale": rationale,
        "status": "ACTIVE",
    })
    db.votes[row["id"]] = row
    svc.sync_vote_counters(offer)
    return object_response(pub(row), 201)


@bp.get("/votes/<vote_id>")
def read_vote(vote_id):
    mw.authenticate(VOTE_ROLES)
    return object_response(pub(lk.get_vote(vote_id)))


@bp.get("/votes")
def list_votes():
    mw.authenticate(VOTE_ROLES)
    rows = list(db.votes.values())
    rows = listing.eq_filter(rows, "offer_id")
    rows = listing.eq_filter(rows, "status")
    round_number = mw.query_int("round_number")
    if round_number is not None:
        rows = [r for r in rows if r["round_number"] == round_number]
    return listing.paged(rows)
