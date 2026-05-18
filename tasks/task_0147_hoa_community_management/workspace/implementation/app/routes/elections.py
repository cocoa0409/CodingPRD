"""Election, Candidate, Ballot endpoints."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, g, jsonify

from ..auth import require_roles
from ..envelope import success_object
from ..errors import (
    APIError,
    err_duplicate_ballot,
    err_forbidden,
    err_invalid_state,
    err_nomination_closed,
    err_voter_ineligible,
    err_voting_closed,
)
from ..serializers import serialize_ballot, serialize_candidate, serialize_election
from ..services.clock_sweep import run_sweep
from ..services.common import (
    bump_version,
    check_version,
    compute_eligible_to_vote,
    require,
)
from ..store import store
from ..util import new_uuid, parse_iso8601
from ._helpers import as_decimal, get_json_body, get_version, require_field

bp = Blueprint("elections", __name__)

VALID_SEATS = {"PRESIDENT", "TREASURER", "SECRETARY", "DIRECTOR"}


@bp.route("/hoa/elections/<election_id>", methods=["GET"])
@require_roles(["Member", "SecretaryRole", "TreasurerRole", "PresidentRole", "DirectorRole"])
def get_election(election_id: str):
    run_sweep()
    e = require("elections", election_id)
    return jsonify(success_object(serialize_election(e))), 200


@bp.route("/hoa/elections", methods=["POST"])
@require_roles(["PresidentRole"])
def create_election():
    body = get_json_body()
    seat = require_field(body, "seat")
    if seat not in VALID_SEATS:
        raise APIError("ERR_INVALID_STATE", "seat must be a valid board seat", 409)

    nom_open = parse_iso8601(require_field(body, "nomination_open_at"))
    vot_open = parse_iso8601(require_field(body, "voting_open_at"))
    vot_close = parse_iso8601(require_field(body, "voting_close_at"))

    if not (vot_open > nom_open):
        raise APIError("ERR_INVALID_STATE", "voting_open_at must be > nomination_open_at", 409)
    if not (vot_close > vot_open):
        raise APIError("ERR_INVALID_STATE", "voting_close_at must be > voting_open_at", 409)

    quorum_pct = body.get("quorum_pct", 0.40)
    q = as_decimal(quorum_pct, "quorum_pct")
    if q < Decimal("0.10") or q > Decimal("1.00"):
        raise APIError("ERR_INVALID_STATE", "quorum_pct must be in [0.10, 1.00]", 409)

    s = store()
    now = s.now()
    e = {
        "id": new_uuid(),
        "seat": seat,
        "nomination_open_at": nom_open,
        "voting_open_at": vot_open,
        "voting_close_at": vot_close,
        "quorum_pct": float(q),
        "eligible_voter_count_at_open": None,
        "status": "NOMINATION",
        "winner_candidate_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    s.insert("elections", e)
    return jsonify(success_object(serialize_election(e))), 201


@bp.route("/hoa/elections/<election_id>/candidates", methods=["POST"])
@require_roles(["Member"])
def register_candidate(election_id: str):
    election = require("elections", election_id)
    body = get_json_body()
    member_id = require_field(body, "member_id")

    if member_id != g.user_id:
        raise err_forbidden("member_id must equal X-User-ID")

    member = require("members", member_id)

    # Refresh elections by sweep first
    run_sweep()
    election = require("elections", election_id)

    s = store()
    now = s.now()
    if not (election["nomination_open_at"] <= now < election["voting_open_at"]):
        raise err_nomination_closed()

    member["eligible_to_vote"] = compute_eligible_to_vote(member)
    if not member.get("eligible_to_vote", False):
        raise err_voter_ineligible("Candidate must be eligible_to_vote")

    c = {
        "id": new_uuid(),
        "election_id": election_id,
        "member_id": member_id,
        "nominated_at": now,
        "vote_count": 0,
        "created_at": now,
    }
    s.insert("candidates", c)
    return jsonify(success_object(serialize_candidate(c))), 201


@bp.route("/hoa/elections/<election_id>/ballots", methods=["POST"])
@require_roles(["Member"])
def cast_ballot(election_id: str):
    election = require("elections", election_id)
    body = get_json_body()
    voter_member_id = require_field(body, "voter_member_id")
    candidate_id = require_field(body, "candidate_id")

    if voter_member_id != g.user_id:
        raise err_forbidden("voter_member_id must equal X-User-ID")

    voter = require("members", voter_member_id)

    # Refresh election status first
    run_sweep()
    election = require("elections", election_id)

    s = store()
    now = s.now()

    # Eligibility now + at snapshot
    voter["eligible_to_vote"] = compute_eligible_to_vote(voter)
    if not voter.get("eligible_to_vote", False):
        raise err_voter_ineligible("Voter is not currently eligible")
    snapshot = election.get("eligible_voter_ids_at_open")
    if snapshot is not None and voter_member_id not in snapshot:
        raise err_voter_ineligible("Voter was not eligible at voting_open_at snapshot")

    # Voting window check
    if election["status"] != "VOTING":
        raise err_voting_closed()
    if not (election["voting_open_at"] <= now < election["voting_close_at"]):
        raise err_voting_closed()

    # Duplicate ballot
    for b in s.ballots.values():
        if b["election_id"] == election_id and b["voter_member_id"] == voter_member_id:
            raise err_duplicate_ballot()

    candidate = require("candidates", candidate_id)
    if candidate["election_id"] != election_id:
        raise APIError("ERR_NOT_FOUND", "candidate does not belong to this election", 404)

    b = {
        "id": new_uuid(),
        "election_id": election_id,
        "voter_member_id": voter_member_id,
        "candidate_id": candidate_id,
        "created_at": now,
    }
    s.insert("ballots", b)
    candidate["vote_count"] = candidate.get("vote_count", 0) + 1

    return jsonify(success_object(serialize_ballot(b))), 201


@bp.route("/hoa/elections/<election_id>/certify", methods=["POST"])
@require_roles(["SecretaryRole"])
def certify_election(election_id: str):
    election = require("elections", election_id)
    body = get_json_body()
    version = get_version(body)
    check_version(election, version)

    # Make sure tally has run
    run_sweep()
    election = require("elections", election_id)

    if election["status"] != "TALLIED":
        raise err_invalid_state(f"Election is {election['status']}, cannot certify")
    if not election.get("winner_candidate_id"):
        raise err_invalid_state("No winner to certify")

    s = store()
    now = s.now()
    winner_candidate = s.candidates.get(election["winner_candidate_id"])
    if winner_candidate is None:
        raise err_invalid_state("Winner candidate missing")
    winner_member = s.members.get(winner_candidate["member_id"])
    if winner_member is None:
        raise err_invalid_state("Winner member missing")

    seat = election["seat"]
    # Demote any prior holder
    for m in s.members.values():
        if m["id"] != winner_member["id"] and m.get("board_role") == seat:
            m["board_role"] = "NONE"
            bump_version(m, now)

    winner_member["board_role"] = seat
    bump_version(winner_member, now)

    election["status"] = "CERTIFIED"
    bump_version(election, now)

    return jsonify(success_object(serialize_election(election))), 200
