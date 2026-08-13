"""Proposal endpoints: create/list/read/withdraw plus computed tabulation (PRD §3.4)."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    raise_err,
    ERR_DUPLICATE_PROPOSAL_NUMBER,
    ERR_INVALID_MEETING_STATE,
    ERR_INVALID_REQUEST,
    ERR_MEETING_NOT_FOUND,
    ERR_PROPOSAL_NOT_ACTIVE,
    ERR_PROPOSAL_NOT_FOUND,
)
from middleware import require_roles
from response import success_object, success_list
from services.serializers import serialize, serialize_list
from services.tabulation import compute_tabulation
from util import (
    apply_filters,
    get_json_body,
    optional_enum,
    paginate,
    parse_pagination,
    require_enum,
    require_field,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("proposals", __name__)

PROPOSAL_TYPES = {"DIRECTOR_ELECTION", "SAY_ON_PAY", "RATIFICATION", "SHAREHOLDER_PROPOSAL"}
VOTE_STANDARDS = {"MAJORITY_OF_VOTES_CAST", "MAJORITY_OF_OUTSTANDING", "PLURALITY"}
BOARD_RECOMMENDATIONS = {"FOR", "AGAINST", "NO_RECOMMENDATION"}
TABULATION_VARIANTS = {"UNOFFICIAL", "CERTIFIED"}


def get_proposal_or_404(proposal_id: str) -> dict:
    proposal = db.proposals.get(proposal_id)
    if proposal is None:
        raise_err(ERR_PROPOSAL_NOT_FOUND, "Proposal id does not exist")
    return proposal


@bp.route("/proxy/proposals", methods=["POST"])
@require_roles("ProxyAdministrator")
def create_proposal(_user_id: str, _role: str):
    body = get_json_body()
    meeting_id = require_field(body, "meeting_id")
    meeting = db.meetings.get(meeting_id)
    if meeting is None:
        raise_err(ERR_MEETING_NOT_FOUND, "Meeting id does not exist")
    if meeting["status"] not in ("DRAFT", "RECORD_DATE_LOCKED"):
        raise_err(
            ERR_INVALID_MEETING_STATE,
            "Proposals may only be created while the meeting is DRAFT or RECORD_DATE_LOCKED",
        )

    proposal_number = require_field(body, "proposal_number")
    if isinstance(proposal_number, bool) or not isinstance(proposal_number, int):
        raise_err(ERR_INVALID_REQUEST, "proposal_number must be an integer")
    if any(
        p["meeting_id"] == meeting_id and p["proposal_number"] == proposal_number
        for p in db.proposals.values()
    ):
        raise_err(
            ERR_DUPLICATE_PROPOSAL_NUMBER,
            "proposal_number already exists within the meeting",
        )

    title = require_string(body, "title")
    proposal_type = require_enum(body, "proposal_type", PROPOSAL_TYPES)
    vote_standard = require_enum(body, "vote_standard", VOTE_STANDARDS)
    board_recommendation = optional_enum(
        body, "board_recommendation", BOARD_RECOMMENDATIONS, "FOR"
    )

    proposal = {
        "meeting_id": meeting_id,
        "proposal_number": proposal_number,
        "title": title,
        "proposal_type": proposal_type,
        "vote_standard": vote_standard,
        "board_recommendation": board_recommendation,
        "status": "DRAFT",
    }
    db.stamp_new(proposal)
    db.proposals[proposal["id"]] = proposal
    return success_object(serialize(proposal), 201)


@bp.route("/proxy/proposals", methods=["GET"])
@require_roles(
    "ProxyAdministrator", "TransferAgent", "InspectorOfElection", "Shareholder", "Broker"
)
def list_proposals(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.proposals.values()))
    items = apply_filters(items, ["meeting_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/proxy/proposals/<proposal_id>", methods=["GET"])
@require_roles(
    "ProxyAdministrator", "TransferAgent", "InspectorOfElection", "Shareholder", "Broker"
)
def get_proposal(proposal_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_proposal_or_404(proposal_id)))


@bp.route("/proxy/proposals/<proposal_id>/withdraw", methods=["POST"])
@require_roles("ProxyAdministrator")
def withdraw_proposal(proposal_id: str, _user_id: str, _role: str):
    proposal = get_proposal_or_404(proposal_id)
    if proposal["status"] not in ("DRAFT", "ACTIVE"):
        raise_err(
            ERR_PROPOSAL_NOT_ACTIVE,
            "Only a DRAFT or ACTIVE proposal may be withdrawn",
        )
    was_active = proposal["status"] == "ACTIVE"
    proposal["status"] = "WITHDRAWN"
    db.touch(proposal)
    if was_active:
        # Supersede every VALIDATED vote instruction on the proposal.
        for vote in db.votes.values():
            if vote["proposal_id"] == proposal_id and vote["status"] == "VALIDATED":
                vote["status"] = "SUPERSEDED"
                db.touch(vote)
    return success_object(serialize(proposal))


@bp.route("/proxy/proposals/<proposal_id>/tabulation", methods=["GET"])
@require_roles("ProxyAdministrator", "TransferAgent", "InspectorOfElection")
def get_tabulation(proposal_id: str, _user_id: str, _role: str):
    proposal = get_proposal_or_404(proposal_id)
    variant = request.args.get("variant") or "UNOFFICIAL"
    if variant not in TABULATION_VARIANTS:
        raise_err(ERR_INVALID_REQUEST, "variant must be UNOFFICIAL or CERTIFIED")
    return success_object(compute_tabulation(proposal, variant))
