"""Budget proposals and their weighted ballot (PRD section 3.3)."""

from flask import Blueprint

import calc
import response
import serializers
import validation
from db import base_record, db, touch
from errors import ApiError
from middleware import api, current_user_id, own_body_member, raw_body
from routes import common
from services import conference_service, member_service

bp = Blueprint("budgets", __name__)

PROPOSAL_READ_ROLES = (
    "Commissioner",
    "FinanceOfficer",
    "Treasurer",
    "Auditor",
    "ComplianceOfficer",
    "PlatformAdmin",
    "MemberRepresentative",
)

BALLOT_READ_ROLES = (
    "Commissioner",
    "FinanceOfficer",
    "ComplianceOfficer",
    "Auditor",
    "PlatformAdmin",
    "MemberRepresentative",
)

CHOICES = ("FOR", "AGAINST", "ABSTAIN")


@bp.route("/budget-proposals", methods=["POST"])
@api(("FinanceOfficer",))
def create_proposal():
    body = raw_body()
    conference_id = validation.get_id(body, "conference_id")
    fiscal_year = validation.get_int(body, "fiscal_year", minimum=None)
    operating = validation.get_int(body, "proposed_operating_expense_cents")
    governance = validation.get_int(body, "proposed_governance_expense_cents")
    validation.get_optional_str(body, "note")

    proposal = base_record()
    proposal.update(
        {
            "conference_id": conference_id,
            "fiscal_year": fiscal_year,
            "proposed_operating_expense_cents": operating,
            "proposed_governance_expense_cents": governance,
            "status": "DRAFT",
            "required_approval_bps": calc.BUDGET_APPROVAL_BPS,
            "eligible_weight_bps": 0,
            "cast_weight_bps": 0,
            "for_weight_bps": 0,
            "against_weight_bps": 0,
            "quorum_met": False,
            "approval_ratio_bps": 0,
            "prepared_by_user_id": current_user_id(),
            "approved_by_user_id": None,
        }
    )
    db.budget_proposals[proposal["id"]] = proposal
    return response.single(serializers.budget_proposal(proposal), 201)


@bp.route("/budget-proposals/<proposal_id>", methods=["GET"])
@api(PROPOSAL_READ_ROLES)
def read_proposal(proposal_id):
    return response.single(
        serializers.budget_proposal(common.get_proposal(proposal_id))
    )


@bp.route("/budget-proposals", methods=["GET"])
@api(PROPOSAL_READ_ROLES)
def list_proposals():
    criteria = {
        "conference_id": common.string_filter("conference_id"),
        "fiscal_year": common.int_filter("fiscal_year"),
        "status": common.string_filter("status"),
    }
    return common.listing(
        list(db.budget_proposals.values()),
        serializers.budget_proposal,
        criteria=criteria,
    )


@bp.route("/budget-proposals/<proposal_id>/open-voting", methods=["POST"])
@api(("FinanceOfficer",))
def open_proposal_voting(proposal_id):
    proposal = common.get_proposal(proposal_id)
    if proposal["status"] != "DRAFT":
        raise ApiError("ERR_PROPOSAL_STATE_INVALID")
    if not member_service.has_any_voter(proposal["conference_id"]):
        raise ApiError("ERR_MEMBER_NOT_ELIGIBLE_TO_VOTE")
    proposal["status"] = "VOTING"
    proposal["required_approval_bps"] = calc.BUDGET_APPROVAL_BPS
    touch(proposal)
    return response.single(serializers.budget_proposal(proposal))


def _proposal_ballots(proposal_id, statuses=None):
    return [
        ballot
        for ballot in db.ballots.values()
        if ballot["budget_proposal_id"] == proposal_id
        and (statuses is None or ballot["status"] in statuses)
    ]


@bp.route("/budget-proposals/<proposal_id>/ballots", methods=["POST"])
@api(("MemberRepresentative",), owner=own_body_member)
def cast_proposal_ballot(proposal_id):
    proposal = common.get_proposal(proposal_id)
    body = raw_body()

    member_id = validation.get_id(body, "member_id")
    choice = validation.get_enum(body, "choice", CHOICES)

    member = common.get_member(member_id)

    if proposal["status"] != "VOTING":
        raise ApiError("ERR_PROPOSAL_STATE_INVALID")
    if member["voting_weight_bps"] <= 0:
        raise ApiError("ERR_MEMBER_NOT_ELIGIBLE_TO_VOTE")
    for existing in _proposal_ballots(proposal["id"], statuses=("CAST",)):
        if existing["member_id"] == member_id:
            raise ApiError("ERR_DUPLICATE_BALLOT")

    ballot = base_record(versioned=False)
    ballot.update(
        {
            "membership_action_id": None,
            "budget_proposal_id": proposal["id"],
            "member_id": member_id,
            "choice": choice,
            "weight_bps": member["voting_weight_bps"],
            "status": "CAST",
            "cast_by_user_id": current_user_id(),
        }
    )
    db.ballots[ballot["id"]] = ballot
    return response.single(serializers.ballot(ballot), 201)


@bp.route("/budget-proposals/<proposal_id>/ballots", methods=["GET"])
@api(BALLOT_READ_ROLES)
def list_proposal_ballots(proposal_id):
    common.get_proposal(proposal_id)
    criteria = {
        "member_id": common.string_filter("member_id"),
        "status": common.string_filter("status"),
    }
    return common.listing(
        _proposal_ballots(proposal_id), serializers.ballot, criteria=criteria
    )


@bp.route("/budget-proposals/<proposal_id>/close-voting", methods=["POST"])
@api(("FinanceOfficer",))
def close_proposal_voting(proposal_id):
    proposal = common.get_proposal(proposal_id)
    conference = db.conference

    if proposal["status"] != "VOTING":
        raise ApiError("ERR_PROPOSAL_STATE_INVALID")

    result = calc.tally(
        member_service.eligible_voting_weight_bps(proposal["conference_id"]),
        _proposal_ballots(proposal["id"], statuses=("CAST",)),
        calc.QUORUM_WEIGHT_BPS,
        calc.BUDGET_APPROVAL_BPS,
    )
    outcome = result.pop("outcome")
    proposal.update(result)
    proposal["required_approval_bps"] = calc.BUDGET_APPROVAL_BPS
    proposal["status"] = "APPROVED" if outcome == "APPROVED" else "REJECTED"

    if outcome == "APPROVED":
        proposal["approved_by_user_id"] = current_user_id()
        conference["approved_operating_expense_cents"] = proposal[
            "proposed_operating_expense_cents"
        ]
        conference["approved_governance_expense_cents"] = proposal[
            "proposed_governance_expense_cents"
        ]
        conference_service.derive_reserve_posture(conference)
        if conference["governance_status"] == "FORMING":
            conference["governance_status"] = "OPERATING"
        touch(conference)

    touch(proposal)
    return response.single(serializers.budget_proposal(proposal))
