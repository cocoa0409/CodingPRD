"""VoteChallenge endpoints (PRD §3.8), including the UPHELD cascade:

vote INVALIDATED -> tabulation/quorum recompute -> any DRAFT or SIGNED
certification of the meeting SUPERSEDED; if a SIGNED certification was
superseded, the meeting reverts RESULTS_CERTIFIED -> MEETING_HELD and its
PASSED/FAILED proposals return to ACTIVE.
"""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CHALLENGE_NOT_OPEN,
    ERR_CHALLENGE_NOT_FOUND,
    ERR_CROSS_MEETING_REFERENCE,
    ERR_INVALID_MEETING_STATE,
    ERR_MEETING_NOT_FOUND,
    ERR_VOTE_NOT_ALTERABLE,
    ERR_VOTE_NOT_FOUND,
)
from middleware import require_roles
from response import success_object, success_list
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    optional_string,
    paginate,
    parse_pagination,
    require_enum,
    require_field,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("challenges", __name__)

RULINGS = {"UPHELD", "OVERRULED"}
CHALLENGEABLE_MEETING_STATES = {"MEETING_IN_PROGRESS", "MEETING_HELD", "RESULTS_CERTIFIED"}


def get_challenge_or_404(challenge_id: str) -> dict:
    challenge = db.challenges.get(challenge_id)
    if challenge is None:
        raise_err(ERR_CHALLENGE_NOT_FOUND, "VoteChallenge id does not exist")
    return challenge


def supersede_certifications_on_challenge(meeting_id: str) -> None:
    """Compensation cascade shared by UPHELD adjudication: supersede any
    DRAFT or SIGNED certification; a superseded SIGNED certification reverts
    the meeting to MEETING_HELD and its PASSED/FAILED proposals to ACTIVE."""
    meeting = db.meetings.get(meeting_id)
    signed_superseded = False
    for cert in db.certifications.values():
        if cert["meeting_id"] == meeting_id and cert["status"] in ("DRAFT", "SIGNED"):
            if cert["status"] == "SIGNED":
                signed_superseded = True
            cert["status"] = "SUPERSEDED"
            db.touch(cert)
    if signed_superseded and meeting is not None and meeting["status"] == "RESULTS_CERTIFIED":
        meeting["status"] = "MEETING_HELD"
        db.touch(meeting)
        for proposal in db.proposals.values():
            if proposal["meeting_id"] == meeting_id and proposal["status"] in (
                "PASSED",
                "FAILED",
            ):
                proposal["status"] = "ACTIVE"
                db.touch(proposal)


@bp.route("/proxy/vote-challenges", methods=["POST"])
@require_roles("InspectorOfElection")
def create_challenge(_user_id: str, _role: str):
    body = get_json_body()

    # Existence (precedence 3).
    meeting_id = require_field(body, "meeting_id")
    meeting = db.meetings.get(meeting_id)
    if meeting is None:
        raise_err(ERR_MEETING_NOT_FOUND, "Meeting id does not exist")
    vote_instruction_id = require_field(body, "vote_instruction_id")
    vote = db.votes.get(vote_instruction_id)
    if vote is None:
        raise_err(ERR_VOTE_NOT_FOUND, "VoteInstruction id does not exist")

    # State (precedence 4): meeting gate first, then the target instruction.
    if meeting["status"] not in CHALLENGEABLE_MEETING_STATES:
        raise_err(
            ERR_INVALID_MEETING_STATE,
            "Challenges require MEETING_IN_PROGRESS, MEETING_HELD, or RESULTS_CERTIFIED",
        )
    if vote["status"] != "VALIDATED":
        raise_err(
            ERR_VOTE_NOT_ALTERABLE,
            "Only a VALIDATED vote instruction may be challenged",
        )

    # Cross-meeting referential integrity (precedence 7).
    if vote["meeting_id"] != meeting_id:
        raise_err(
            ERR_CROSS_MEETING_REFERENCE,
            "vote_instruction_id must belong to the request's meeting",
        )

    # Shape (precedence 10).
    reason = require_string(body, "reason")

    challenge = {
        "meeting_id": meeting_id,
        "vote_instruction_id": vote_instruction_id,
        "reason": reason,
        "ruling": None,
        "resolution_note": None,
        "status": "OPEN",
    }
    db.stamp_new(challenge)
    db.challenges[challenge["id"]] = challenge
    return success_object(serialize(challenge), 201)


@bp.route("/proxy/vote-challenges", methods=["GET"])
@require_roles("ProxyAdministrator", "TransferAgent", "InspectorOfElection")
def list_challenges(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.challenges.values()))
    items = apply_filters(items, ["meeting_id", "vote_instruction_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/proxy/vote-challenges/<challenge_id>", methods=["GET"])
@require_roles("ProxyAdministrator", "TransferAgent", "InspectorOfElection")
def get_challenge(challenge_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_challenge_or_404(challenge_id)))


@bp.route("/proxy/vote-challenges/<challenge_id>/adjudicate", methods=["POST"])
@require_roles("InspectorOfElection")
def adjudicate_challenge(challenge_id: str, _user_id: str, _role: str):
    challenge = get_challenge_or_404(challenge_id)
    if challenge["status"] != "OPEN":
        raise_err(ERR_CHALLENGE_NOT_OPEN, "Only an OPEN challenge may be adjudicated")
    body = get_json_body()
    ruling = require_enum(body, "ruling", RULINGS)
    resolution_note = optional_string(body, "resolution_note")

    challenge["ruling"] = ruling
    challenge["resolution_note"] = resolution_note
    challenge["status"] = ruling
    db.touch(challenge)

    if ruling == "UPHELD":
        vote = db.votes.get(challenge["vote_instruction_id"])
        if vote is not None and vote["status"] == "VALIDATED":
            vote["status"] = "INVALIDATED"
            db.touch(vote)
        # Cascade: tabulation and quorum are recomputed on read; supersede any
        # non-superseded certification (SIGNED also reverts the meeting).
        supersede_certifications_on_challenge(challenge["meeting_id"])

    return success_object(serialize(challenge))
