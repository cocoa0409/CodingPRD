"""VoteInstruction endpoints (PRD §3.4): latest-valid-vote-wins event stream."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_ACCOUNT_NOT_FOUND,
    ERR_CHOICE_NOT_ALLOWED,
    ERR_CROSS_MEETING_REFERENCE,
    ERR_FORBIDDEN,
    ERR_INVALID_CONTROL_NUMBER,
    ERR_INVALID_REQUEST,
    ERR_MEETING_NOT_FOUND,
    ERR_PROPOSAL_NOT_ACTIVE,
    ERR_PROPOSAL_NOT_FOUND,
    ERR_SHARES_EXCEED_HELD,
    ERR_VOTE_NOT_ALTERABLE,
    ERR_VOTE_NOT_FOUND,
    ERR_VOTING_NOT_OPEN,
)
from middleware import require_roles
from response import success_object, success_list
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    optional_field,
    paginate,
    parse_pagination,
    require_field,
    sort_by_created_at,
)

bp = Blueprint("votes", __name__)

ALL_CHANNELS = {"INTERNET", "PHONE", "MAIL", "BROKER", "IN_PERSON"}
REMOTE_CHANNELS = {"INTERNET", "PHONE", "MAIL"}
ROLE_CHANNELS = {
    "Shareholder": {"INTERNET", "PHONE", "MAIL"},
    "Broker": {"BROKER"},
    "ProxyAdministrator": {"IN_PERSON"},
}
ALL_CHOICES = {"FOR", "AGAINST", "ABSTAIN", "WITHHOLD"}
VOTING_OPEN_STATES = {"VOTING_OPEN", "MEETING_IN_PROGRESS"}


def get_vote_or_404(vote_id: str) -> dict:
    vote = db.votes.get(vote_id)
    if vote is None:
        raise_err(ERR_VOTE_NOT_FOUND, "VoteInstruction id does not exist")
    return vote


@bp.route("/proxy/vote-instructions", methods=["POST"])
@require_roles("Shareholder", "Broker", "ProxyAdministrator")
def create_vote(_user_id: str, _role: str):
    body = get_json_body()

    # Authorization (precedence 2): channel-role matrix, then Shareholder
    # ownership of the account it votes on. The matrix check applies to
    # declared channel values; undeclared channel strings fall through to the
    # shape check at precedence 10.
    channel = body.get("channel")
    if channel in ALL_CHANNELS and channel not in ROLE_CHANNELS[_role]:
        raise_err(ERR_FORBIDDEN, f"Channel {channel} is not permitted for role {_role}")
    if _role == "Shareholder":
        account_id_raw = body.get("account_id")
        if account_id_raw is not None and account_id_raw != _user_id:
            raise_err(ERR_FORBIDDEN, "Shareholder may vote only on its own account")

    # Existence (precedence 3), body references in input order.
    meeting_id = require_field(body, "meeting_id")
    meeting = db.meetings.get(meeting_id)
    if meeting is None:
        raise_err(ERR_MEETING_NOT_FOUND, "Meeting id does not exist")
    proposal_id = require_field(body, "proposal_id")
    proposal = db.proposals.get(proposal_id)
    if proposal is None:
        raise_err(ERR_PROPOSAL_NOT_FOUND, "Proposal id does not exist")
    account_id = require_field(body, "account_id")
    account = db.accounts.get(account_id)
    if account is None:
        raise_err(ERR_ACCOUNT_NOT_FOUND, "ShareholderAccount id does not exist")

    # State (precedence 4): meeting must accept votes, proposal must be ACTIVE.
    if meeting["status"] not in VOTING_OPEN_STATES:
        raise_err(ERR_VOTING_NOT_OPEN, "Voting is accepted only while VOTING_OPEN or MEETING_IN_PROGRESS")
    if proposal["status"] != "ACTIVE":
        raise_err(ERR_PROPOSAL_NOT_ACTIVE, "Vote attempted on a proposal that is not ACTIVE")

    # Cross-meeting referential integrity (precedence 7).
    if proposal["meeting_id"] != meeting_id or account["meeting_id"] != meeting_id:
        raise_err(
            ERR_CROSS_MEETING_REFERENCE,
            "proposal_id and account_id must belong to the request's meeting",
        )

    # Domain constraints (precedence 8): control number, share range, choice.
    if channel in REMOTE_CHANNELS:
        control_number = body.get("control_number")
        if not control_number or control_number != account["control_number"]:
            raise_err(
                ERR_INVALID_CONTROL_NUMBER,
                "Remote-channel votes must carry the account's control_number",
            )
    shares_voted = optional_field(body, "shares_voted", account["shares_held"])
    if isinstance(shares_voted, bool) or not isinstance(shares_voted, int):
        raise_err(ERR_INVALID_REQUEST, "shares_voted must be an integer")
    if shares_voted <= 0 or shares_voted > account["shares_held"]:
        raise_err(
            ERR_SHARES_EXCEED_HELD,
            "shares_voted must be greater than zero and no more than shares_held",
        )
    choice = body.get("choice")
    if choice in ALL_CHOICES:
        if proposal["proposal_type"] == "DIRECTOR_ELECTION":
            if choice not in ("FOR", "WITHHOLD"):
                raise_err(
                    ERR_CHOICE_NOT_ALLOWED,
                    "DIRECTOR_ELECTION proposals accept only FOR or WITHHOLD",
                )
        elif choice == "WITHHOLD":
            raise_err(
                ERR_CHOICE_NOT_ALLOWED,
                "WITHHOLD is only available on DIRECTOR_ELECTION proposals",
            )

    # Body shape (precedence 10).
    if channel not in ALL_CHANNELS:
        raise_err(ERR_INVALID_REQUEST, f"channel must be one of {sorted(ALL_CHANNELS)}")
    if choice not in ALL_CHOICES:
        raise_err(ERR_INVALID_REQUEST, f"choice must be one of {sorted(ALL_CHOICES)}")

    # Latest-valid-vote-wins: supersede the prior live instruction, if any.
    for prior in db.votes.values():
        if (
            prior["account_id"] == account_id
            and prior["proposal_id"] == proposal_id
            and prior["status"] == "VALIDATED"
        ):
            prior["status"] = "SUPERSEDED"
            db.touch(prior)

    vote = {
        "meeting_id": meeting_id,
        "proposal_id": proposal_id,
        "account_id": account_id,
        "channel": channel,
        "choice": choice,
        "shares_voted": shares_voted,
        "control_number": optional_field(body, "control_number"),
        "status": "VALIDATED",
    }
    db.stamp_new(vote)
    db.votes[vote["id"]] = vote
    return success_object(serialize(vote), 201)


@bp.route("/proxy/vote-instructions", methods=["GET"])
@require_roles(
    "ProxyAdministrator", "TransferAgent", "InspectorOfElection", "Shareholder", "Broker"
)
def list_votes(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.votes.values()))
    if _role == "Shareholder":
        # Shareholder sees only its own account's votes.
        items = [v for v in items if v["account_id"] == _user_id]
    items = apply_filters(items, ["meeting_id", "proposal_id", "account_id", "channel", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/proxy/vote-instructions/<vote_id>", methods=["GET"])
@require_roles("ProxyAdministrator", "TransferAgent", "InspectorOfElection", "Shareholder")
def get_vote(vote_id: str, _user_id: str, _role: str):
    vote = get_vote_or_404(vote_id)
    if _role == "Shareholder" and vote["account_id"] != _user_id:
        raise_err(ERR_FORBIDDEN, "Shareholder may read only its own votes")
    return success_object(serialize(vote))


@bp.route("/proxy/vote-instructions/<vote_id>/revoke", methods=["POST"])
@require_roles("Shareholder", "ProxyAdministrator")
def revoke_vote(vote_id: str, _user_id: str, _role: str):
    vote = get_vote_or_404(vote_id)
    if _role == "Shareholder" and vote["account_id"] != _user_id:
        raise_err(ERR_FORBIDDEN, "Shareholder may revoke only its own votes")
    if vote["status"] != "VALIDATED":
        raise_err(
            ERR_VOTE_NOT_ALTERABLE,
            "Only a VALIDATED vote instruction may be revoked",
        )
    meeting = db.meetings.get(vote["meeting_id"])
    if meeting is None or meeting["status"] not in VOTING_OPEN_STATES:
        raise_err(
            ERR_VOTING_NOT_OPEN,
            "Revocation is accepted only while VOTING_OPEN or MEETING_IN_PROGRESS",
        )
    vote["status"] = "REVOKED"
    db.touch(vote)
    return success_object(serialize(vote))
