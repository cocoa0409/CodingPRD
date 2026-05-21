"""Absentee ballot endpoints."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import current_user, require_roles
from ..envelope import success_object
from ..errors import (
    err_absentee_already_issued,
    err_bad_request,
    err_deadline_passed,
    err_forbidden,
    err_invalid_state,
    err_return_late,
    err_voter_not_active,
)
from ..serializers import serialize_absentee
from ..services.cascades import cascade_absentee_accept_on_return
from ..services.common import bump_version, check_version, require
from ..store import store
from ..util import new_uuid
from ._helpers import as_str, get_json_body, get_version, require_field

bp = Blueprint("absentee", __name__)

REASON_CODES = {"MILITARY", "OVERSEAS", "DISABILITY", "ABSENT", "NO_REASON"}
SIG_MATCH = {"MATCH", "MISMATCH", "MISSING"}


@bp.route("/voters/<voter_id>/absentee-ballots", methods=["POST"])
@require_roles(["Voter", "RegistrarClerk"])
def request_absentee(voter_id: str):
    v = require("voters", voter_id)
    uid, role = current_user()
    if role == "Voter" and v["id"] != uid:
        raise err_forbidden("Voter can only act on their own row")

    body = get_json_body()
    election_id = as_str(require_field(body, "election_id"), "election_id")
    reason_code = body.get("reason_code", "NO_REASON")
    if reason_code not in REASON_CODES:
        raise err_bad_request("reason_code is not a valid value")

    s = store()
    election = require("elections", election_id)
    now = s.now()
    if now > election["absentee_request_deadline"]:
        raise err_deadline_passed("absentee_request_deadline has passed")

    # Uniqueness: at most one AbsenteeBallot for (voter, election) in
    # {REQUESTED, ISSUED, RETURNED, ACCEPTED, CURED}
    blocking = {"REQUESTED", "ISSUED", "RETURNED", "ACCEPTED", "CURED"}
    for b in s.absentee_ballots.values():
        if b.get("voter_id") == voter_id and b.get("election_id") == election_id:
            if b.get("status") in blocking:
                raise err_absentee_already_issued()

    b = {
        "id": new_uuid(),
        "voter_id": voter_id,
        "election_id": election_id,
        "requested_at": now,
        "issued_at": None,
        "returned_at": None,
        "decided_at": None,
        "reason_code": reason_code,
        "signature_match": None,
        "status": "REQUESTED",
        "linked_curing_case_id": None,
        "voter_choice": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    s.insert("absentee_ballots", b)
    return jsonify(success_object(serialize_absentee(b))), 201


@bp.route("/absentee-ballots/<ballot_id>", methods=["GET"])
@require_roles(["Voter", "RegistrarClerk", "ReviewerClerk", "ElectionBoard"])
def get_absentee(ballot_id: str):
    b = require("absentee_ballots", ballot_id)
    uid, role = current_user()
    if role == "Voter":
        # ownership
        if b["voter_id"] != uid:
            raise err_forbidden("Voter can only view their own ballots")
    return jsonify(success_object(serialize_absentee(b))), 200


@bp.route("/absentee-ballots/<ballot_id>/state", methods=["POST"])
@require_roles(["RegistrarClerk"])
def absentee_transition(ballot_id: str):
    b = require("absentee_ballots", ballot_id)
    body = get_json_body()
    to_state = as_str(require_field(body, "to_state"), "to_state")
    version = get_version(body)

    s = store()
    now = s.now()
    from_state = b["status"]
    voter = require("voters", b["voter_id"])
    election = require("elections", b["election_id"])

    if from_state == "REQUESTED" and to_state == "ISSUED":
        if voter.get("status") != "ACTIVE":
            raise err_voter_not_active()
        if now > election["absentee_request_deadline"]:
            raise err_deadline_passed("absentee_request_deadline has passed")
        check_version(b, version)
        b["status"] = "ISSUED"
        b["issued_at"] = now
        bump_version(b, now)

    elif from_state == "RETURNED" and to_state == "REJECTED":
        linked = b.get("linked_curing_case_id")
        if linked:
            cc = s.curing_cases.get(linked)
            if not cc or cc.get("status") not in ("RESOLVED_REJECT", "EXPIRED"):
                raise err_invalid_state("Cannot REJECT while curing case is unresolved")
        check_version(b, version)
        b["status"] = "REJECTED"
        b["decided_at"] = now
        bump_version(b, now)

    else:
        raise err_invalid_state(f"AbsenteeBallot cannot transition {from_state} -> {to_state}")

    return jsonify(success_object(serialize_absentee(b))), 200


@bp.route("/absentee-ballots/<ballot_id>/return", methods=["POST"])
@require_roles(["RegistrarClerk"])
def receive_return(ballot_id: str):
    b = require("absentee_ballots", ballot_id)
    body = get_json_body()
    signature_match = as_str(require_field(body, "signature_match"), "signature_match")
    voter_choice = as_str(require_field(body, "voter_choice"), "voter_choice")
    version = get_version(body)
    if signature_match not in SIG_MATCH:
        raise err_bad_request("signature_match must be MATCH | MISMATCH | MISSING")

    s = store()
    now = s.now()
    election = require("elections", b["election_id"])

    if b["status"] != "ISSUED":
        raise err_invalid_state("AbsenteeBallot must be ISSUED to be returned")
    if now > election["ballot_return_deadline"]:
        raise err_return_late()
    check_version(b, version)

    b["status"] = "RETURNED"
    b["returned_at"] = now
    b["signature_match"] = signature_match
    b["voter_choice"] = voter_choice
    bump_version(b, now)

    if signature_match == "MATCH":
        cascade_absentee_accept_on_return(b, voter_choice)
    else:
        # Open a curing case
        defect = "SIGNATURE_MISMATCH" if signature_match == "MISMATCH" else "SIGNATURE_MISSING"
        cc = {
            "id": new_uuid(),
            "absentee_ballot_id": b["id"],
            "voter_id": b["voter_id"],
            "election_id": b["election_id"],
            "defect_code": defect,
            "round_count": 0,
            "max_rounds": 3,
            "voter_submission_text": None,
            "voter_choice": None,
            "status": "OPEN_PENDING_VOTER",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        s.insert("curing_cases", cc)
        b["linked_curing_case_id"] = cc["id"]
        bump_version(b, now)

    return jsonify(success_object(serialize_absentee(b))), 200
