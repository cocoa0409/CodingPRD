"""Membership actions: the weighted ballot and its negotiation loop (PRD 3.2)."""

from flask import Blueprint

import calc
import response
import serializers
import validation
from db import base_record, db, touch
from errors import ApiError
from middleware import api, current_user_id, own_body_member, raw_body
from routes import common
from services import compliance, member_service

bp = Blueprint("actions", __name__)

ACTION_READ_ROLES = (
    "Commissioner",
    "ComplianceOfficer",
    "Auditor",
    "FinanceOfficer",
    "PlatformAdmin",
    "MemberRepresentative",
)

BALLOT_READ_ROLES = (
    "Commissioner",
    "ComplianceOfficer",
    "Auditor",
    "PlatformAdmin",
    "MemberRepresentative",
)

CHOICES = ("FOR", "AGAINST", "ABSTAIN")

UNPROPOSABLE_MEMBER_STATUSES = ("DEPARTED", "ADMISSION_DENIED")

EXECUTION_MEMBER_STATUS = {"ADMIT": "PETITIONED", "WITHDRAW": "WITHDRAWAL_NOTICED"}


# ---------------------------------------------------------------------------
# POST /membership-actions
# ---------------------------------------------------------------------------


@bp.route("/membership-actions", methods=["POST"])
@api(("Commissioner",))
def propose_action():
    conference = db.conference
    body = raw_body()

    conference_id = validation.get_id(body, "conference_id")
    member_id = validation.get_id(body, "member_id")
    action_type = validation.get_enum(body, "action_type", ("ADMIT", "WITHDRAW"))
    effective_fiscal_year = validation.get_int(
        body, "effective_fiscal_year", minimum=None
    )
    entry_fee_cents = validation.get_int(body, "entry_fee_cents", required=False, default=0)
    rationale = validation.get_optional_str(body, "rationale")

    member = common.get_member(member_id)

    if member["status"] in UNPROPOSABLE_MEMBER_STATUSES:
        raise ApiError("ERR_MEMBER_STATE_INVALID")
    if effective_fiscal_year <= conference["current_fiscal_year"]:
        raise ApiError("ERR_INVALID_EFFECTIVE_YEAR")
    if action_type == "ADMIT" and not _has_approved_budget(conference):
        raise ApiError("ERR_NO_APPROVED_BUDGET")

    action = base_record()
    action.update(
        {
            "conference_id": conference_id,
            "member_id": member_id,
            "action_type": action_type,
            "effective_fiscal_year": effective_fiscal_year,
            "entry_fee_cents": entry_fee_cents,
            "rationale": rationale,
            "status": "PROPOSED",
            # The approval threshold is fixed when the ballot opens.
            "required_approval_bps": None,
            "quorum_weight_bps": calc.QUORUM_WEIGHT_BPS,
            "eligible_weight_bps": 0,
            "cast_weight_bps": 0,
            "for_weight_bps": 0,
            "against_weight_bps": 0,
            "quorum_met": False,
            "approval_ratio_bps": 0,
            "proposed_by_user_id": current_user_id(),
            "closed_by_user_id": None,
            "amend_count": 0,
        }
    )
    db.membership_actions[action["id"]] = action
    return response.single(serializers.membership_action(action), 201)


def _has_approved_budget(conference):
    for proposal in db.budget_proposals.values():
        if (
            proposal["conference_id"] == conference["id"]
            and proposal["fiscal_year"] == conference["current_fiscal_year"]
            and proposal["status"] == "APPROVED"
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


@bp.route("/membership-actions/<action_id>", methods=["GET"])
@api(ACTION_READ_ROLES)
def read_action(action_id):
    return response.single(serializers.membership_action(common.get_action(action_id)))


@bp.route("/membership-actions", methods=["GET"])
@api(ACTION_READ_ROLES)
def list_actions():
    criteria = {
        "conference_id": common.string_filter("conference_id"),
        "member_id": common.string_filter("member_id"),
        "action_type": common.string_filter("action_type"),
        "status": common.string_filter("status"),
    }
    return common.listing(
        list(db.membership_actions.values()),
        serializers.membership_action,
        criteria=criteria,
    )


# ---------------------------------------------------------------------------
# open-voting  |  withdraw
# ---------------------------------------------------------------------------


@bp.route("/membership-actions/<action_id>/open-voting", methods=["POST"])
@api(("Commissioner",))
def open_action_voting(action_id):
    action = common.get_action(action_id)
    if action["status"] != "PROPOSED":
        raise ApiError("ERR_ACTION_STATE_INVALID")
    if not member_service.has_any_voter(action["conference_id"]):
        raise ApiError("ERR_MEMBER_NOT_ELIGIBLE_TO_VOTE")
    action["status"] = "VOTING"
    action["required_approval_bps"] = calc.required_approval_for_action(
        action["action_type"]
    )
    touch(action)
    return response.single(serializers.membership_action(action))


@bp.route("/membership-actions/<action_id>/withdraw", methods=["POST"])
@api(("Commissioner",))
def withdraw_action(action_id):
    action = common.get_action(action_id)
    body = raw_body()
    validation.get_optional_str(body, "reason")
    if action["status"] != "PROPOSED":
        raise ApiError("ERR_ACTION_STATE_INVALID")
    action["status"] = "WITHDRAWN"
    for ballot in _action_ballots(action["id"]):
        ballot["status"] = "VOIDED"
    touch(action)
    return response.single(serializers.membership_action(action))


def _action_ballots(action_id, statuses=None):
    return [
        ballot
        for ballot in db.ballots.values()
        if ballot["membership_action_id"] == action_id
        and (statuses is None or ballot["status"] in statuses)
    ]


# ---------------------------------------------------------------------------
# Ballots
# ---------------------------------------------------------------------------


@bp.route("/membership-actions/<action_id>/ballots", methods=["POST"])
@api(("MemberRepresentative",), owner=own_body_member)
def cast_action_ballot(action_id):
    action = common.get_action(action_id)
    body = raw_body()

    member_id = validation.get_id(body, "member_id")
    choice = validation.get_enum(body, "choice", CHOICES)
    expected_version = validation.get_int(body, "expected_action_version", minimum=None)

    member = common.get_member(member_id)

    if expected_version != action["version"]:
        raise ApiError("ERR_STALE_ACTION_VERSION")
    if action["status"] != "VOTING":
        raise ApiError("ERR_ACTION_STATE_INVALID")
    if member["voting_weight_bps"] <= 0:
        raise ApiError("ERR_MEMBER_NOT_ELIGIBLE_TO_VOTE")
    for existing in _action_ballots(action["id"], statuses=("CAST",)):
        if existing["member_id"] == member_id:
            raise ApiError("ERR_DUPLICATE_BALLOT")

    ballot = base_record(versioned=False)
    ballot.update(
        {
            "membership_action_id": action["id"],
            "budget_proposal_id": None,
            "member_id": member_id,
            "choice": choice,
            "weight_bps": member["voting_weight_bps"],
            "status": "CAST",
            "cast_by_user_id": current_user_id(),
        }
    )
    db.ballots[ballot["id"]] = ballot
    return response.single(serializers.ballot(ballot), 201)


@bp.route("/membership-actions/<action_id>/ballots", methods=["GET"])
@api(BALLOT_READ_ROLES)
def list_action_ballots(action_id):
    common.get_action(action_id)
    criteria = {
        "member_id": common.string_filter("member_id"),
        "status": common.string_filter("status"),
    }
    return common.listing(
        _action_ballots(action_id), serializers.ballot, criteria=criteria
    )


# ---------------------------------------------------------------------------
# amend
# ---------------------------------------------------------------------------


@bp.route("/membership-actions/<action_id>/amend", methods=["POST"])
@api(("Commissioner",))
def amend_action(action_id):
    action = common.get_action(action_id)
    conference = db.conference
    body = raw_body()

    effective_fiscal_year = None
    if "effective_fiscal_year" in body and body["effective_fiscal_year"] is not None:
        effective_fiscal_year = validation.get_int(
            body, "effective_fiscal_year", minimum=None
        )
    entry_fee_cents = validation.get_int(body, "entry_fee_cents", required=False)
    rationale = validation.get_optional_str(body, "rationale", default=Ellipsis)

    if action["status"] != "VOTING":
        raise ApiError("ERR_ACTION_STATE_INVALID")
    if action["amend_count"] >= calc.AMEND_LIMIT:
        raise ApiError("ERR_AMEND_LIMIT_REACHED")
    if (
        effective_fiscal_year is not None
        and effective_fiscal_year <= conference["current_fiscal_year"]
    ):
        raise ApiError("ERR_INVALID_EFFECTIVE_YEAR")

    if effective_fiscal_year is not None:
        action["effective_fiscal_year"] = effective_fiscal_year
    if entry_fee_cents is not None:
        action["entry_fee_cents"] = entry_fee_cents
    if rationale is not Ellipsis:
        action["rationale"] = rationale

    action["status"] = "PROPOSED"
    for ballot in _action_ballots(action["id"], statuses=("CAST",)):
        ballot["status"] = "VOIDED"
    action["cast_weight_bps"] = 0
    action["for_weight_bps"] = 0
    action["against_weight_bps"] = 0
    action["approval_ratio_bps"] = 0
    action["amend_count"] += 1
    touch(action)
    return response.single(serializers.membership_action(action))


# ---------------------------------------------------------------------------
# close-voting
# ---------------------------------------------------------------------------


@bp.route("/membership-actions/<action_id>/close-voting", methods=["POST"])
@api(("ComplianceOfficer", "Commissioner"))
def close_action_voting(action_id):
    action = common.get_action(action_id)

    if action["status"] != "VOTING":
        raise ApiError("ERR_ACTION_STATE_INVALID")
    if current_user_id() == action["proposed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    required = calc.required_approval_for_action(action["action_type"])
    result = calc.tally(
        member_service.eligible_voting_weight_bps(action["conference_id"]),
        _action_ballots(action["id"], statuses=("CAST",)),
        action["quorum_weight_bps"],
        required,
    )
    outcome = result.pop("outcome")
    action.update(result)
    action["required_approval_bps"] = required
    action["closed_by_user_id"] = current_user_id()
    action["status"] = "APPROVED" if outcome == "APPROVED" else "REJECTED"
    touch(action)

    if outcome == "REJECTED" and action["action_type"] == "ADMIT":
        member = db.members.get(action["member_id"])
        if member is not None and member["status"] == "PETITIONED":
            member["status"] = "ADMISSION_DENIED"
            member["voting_weight_bps"] = 0
            touch(member)

    return response.single(serializers.membership_action(action))


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------


@bp.route("/membership-actions/<action_id>/execute", methods=["POST"])
@api(("Commissioner",))
def execute_action(action_id):
    action = common.get_action(action_id)
    conference = db.conference
    member = db.members.get(action["member_id"])

    expected_status = EXECUTION_MEMBER_STATUS[action["action_type"]]
    if action["status"] != "APPROVED":
        raise ApiError("ERR_ACTION_STATE_INVALID")
    if member is None or member["status"] != expected_status:
        raise ApiError("ERR_ACTION_STATE_INVALID")

    if action["action_type"] == "ADMIT":
        if member["entry_fee_paid_cents"] < member["entry_fee_cents"]:
            raise ApiError("ERR_ENTRY_FEE_OUTSTANDING")

    action["status"] = "EXECUTED"
    touch(action)

    if action["action_type"] == "ADMIT":
        member["status"] = "ADMITTED_PHASING"
        member["phase_year"] = 1
        member_service.apply_phase_schedule(member)
        member["voting_weight_bps"] = member["distribution_phase_bps"]
        member["entry_fee_cents"] = action["entry_fee_cents"]
        touch(member)
    else:
        _execute_withdrawal(member, conference)

    return response.single(serializers.membership_action(action))


def _execute_withdrawal(member, conference):
    """The five mandatory hops of PRD section 3.2."""
    # Hop one - the member departs.
    member["status"] = "DEPARTED"
    member["distribution_phase_bps"] = 0
    member["voting_weight_bps"] = 0
    touch(member)

    # Hop two - every scheduled game of the member is cancelled.
    affected = {member["id"]: member}
    cancelled_rivalry_ids = set()
    for game in db.schedule_games.values():
        if game["status"] != "SCHEDULED":
            continue
        if member["id"] not in (game["home_member_id"], game["away_member_id"]):
            continue
        game["status"] = "CANCELLED"
        touch(game)
        if game.get("protected_rivalry_id"):
            cancelled_rivalry_ids.add(game["protected_rivalry_id"])
        for participant_id in (game["home_member_id"], game["away_member_id"]):
            participant = db.members.get(participant_id)
            if participant is not None:
                affected[participant_id] = participant

    # Hop three - rivalries of the member left without a meeting lapse.
    counterparts = []
    for rivalry in db.protected_rivalries.values():
        if member["id"] not in (rivalry["member_a_id"], rivalry["member_b_id"]):
            continue
        if compliance.lapse_rivalry_if_unmet(rivalry):
            counterparts.extend(compliance.counterparts(rivalry))
    # A rivalry satisfied only by a cancelled game also lapses.
    for rivalry_id in cancelled_rivalry_ids:
        rivalry = db.protected_rivalries.get(rivalry_id)
        if rivalry is not None and compliance.lapse_rivalry_if_unmet(rivalry):
            counterparts.extend(compliance.counterparts(rivalry))

    # Hop four - every counterpart's compliance score is recomputed.
    compliance.recompute_many(counterparts)
    for counterpart in counterparts:
        if counterpart is not None:
            affected[counterpart["id"]] = counterpart

    # Hop five - hosting assignments follow the recomputed scores.
    for candidate in affected.values():
        compliance.apply_host_eligibility(candidate)
