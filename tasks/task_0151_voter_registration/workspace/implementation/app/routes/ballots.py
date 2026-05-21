"""In-person ballot casting endpoint."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import require_roles
from ..envelope import success_object
from ..errors import (
    err_bad_request,
    err_double_vote,
    err_invalid_state,
    err_machine_failure,
    err_not_found,
)
from ..serializers import serialize_ballot_cast
from ..services.common import bump_version, check_version, require
from ..services.tally import election_margin
from ..store import store
from ..util import new_uuid
from ._helpers import as_str, get_json_body, get_version, require_field

bp = Blueprint("ballots", __name__)

METHODS = {
    "EARLY_IN_PERSON",
    "ELECTION_DAY_MACHINE",
    "ELECTION_DAY_PROVISIONAL",
    "ABSENTEE",
}


@bp.route("/ballots", methods=["POST"])
@require_roles(["PrecinctOfficer"])
def cast_ballot():
    body = get_json_body()
    voter_id = as_str(require_field(body, "voter_id"), "voter_id")
    precinct_id = as_str(require_field(body, "precinct_id"), "precinct_id")
    method = as_str(require_field(body, "method"), "method")
    voter_choice = as_str(require_field(body, "voter_choice"), "voter_choice")
    machine_id = body.get("machine_id")
    if method not in METHODS:
        raise err_bad_request("method is not a valid value")

    s = store()
    now = s.now()

    voter = require("voters", voter_id)
    precinct = require("precincts", precinct_id)
    election = require("elections", voter["election_id"])

    # Priority 7: double-vote
    for b in s.ballot_casts.values():
        if (
            b.get("voter_id") == voter_id
            and b.get("election_id") == election["id"]
            and b.get("status") != "INVALIDATED"
        ):
            raise err_double_vote()

    # Priority 8: machine-failure rule applies to ELECTION_DAY_MACHINE only
    if method == "ELECTION_DAY_MACHINE":
        # machine_id required
        if not isinstance(machine_id, str) or not machine_id:
            raise err_bad_request("machine_id required when method=ELECTION_DAY_MACHINE")
        # Per the precinct's machine_failure_active flag
        any_down = any(
            m.get("precinct_id") == precinct_id and m.get("status") == "DOWN"
            for m in s.voting_machines.values()
        )
        if any_down:
            raise err_machine_failure()
        # validate machine exists & belongs to this precinct
        machine = s.voting_machines.get(machine_id)
        if not machine:
            raise err_not_found()
        if machine.get("precinct_id") != precinct_id:
            raise err_not_found()
        # First cast triggers READY -> IN_USE
        if machine.get("status") == "READY" and election.get("state") == "ELECTION_DAY":
            machine["status"] = "IN_USE"
            bump_version(machine, now)
    elif machine_id is not None:
        raise err_bad_request("machine_id only valid when method=ELECTION_DAY_MACHINE")

    bc = {
        "id": new_uuid(),
        "precinct_id": precinct_id,
        "voter_id": voter_id,
        "election_id": election["id"],
        "method": method,
        "machine_id": machine_id,
        "absentee_ballot_id": None,
        "voter_choice": voter_choice,
        "cast_at": now,
        "status": "CAST",
        "challenge_reason": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    s.insert("ballot_casts", bc)
    return jsonify(success_object(serialize_ballot_cast(bc))), 201


@bp.route("/ballots/<ballot_id>", methods=["GET"])
@require_roles(["ElectionBoard", "PrecinctOfficer"])
def get_ballot(ballot_id: str):
    b = require("ballot_casts", ballot_id)
    return jsonify(success_object(serialize_ballot_cast(b))), 200


@bp.route("/ballots/<ballot_id>/state", methods=["POST"])
@require_roles(["ElectionBoard"])
def invalidate_ballot(ballot_id: str):
    b = require("ballot_casts", ballot_id)
    body = get_json_body()
    to_state = as_str(require_field(body, "to_state"), "to_state")
    challenge_reason = body.get("challenge_reason")
    version = get_version(body)

    s = store()
    election = require("elections", b["election_id"])
    now = s.now()

    if to_state != "INVALIDATED":
        raise err_invalid_state("Only INVALIDATED is permitted via this endpoint")
    if b["status"] not in ("TALLIED",):
        raise err_invalid_state("Only TALLIED ballots may be manually invalidated")
    if election["state"] not in ("TALLY", "RECOUNT"):
        raise err_invalid_state("Election must be TALLY or RECOUNT")
    if challenge_reason is not None and not isinstance(challenge_reason, str):
        raise err_bad_request("challenge_reason must be a string")
    check_version(b, version)

    b["status"] = "INVALIDATED"
    if challenge_reason:
        b["challenge_reason"] = challenge_reason
    bump_version(b, now)
    return jsonify(success_object(serialize_ballot_cast(b))), 200
