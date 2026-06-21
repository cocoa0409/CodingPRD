"""AbsenteeBallot endpoints (PRD §3.3, §2.8)."""

from flask import Blueprint, g, request

import db
from errors import (
    APIError, invalid_request, not_found, invalid_state, stale_version,
)
import errors as E
from middleware import require_roles
from response import ok_object, ok_array
from services import serialize
from services.common import (
    get_json_body, require_fields, paginate, parse_iso, clock_now,
    recompute_election_counts,
)

bp = Blueprint("ballots", __name__)

REQUEST_TARGETS = {"ISSUED", "RETURNED", "ACCEPTED"}
CURE_REASONS = {"SIGNATURE_MISMATCH", "MISSING_SIGNATURE", "MISSING_WITNESS"}


@bp.route("/absentee-ballots", methods=["POST"])
def create_ballot():
    require_roles("ElectionOfficial", "Voter")
    body = get_json_body()
    require_fields(body, "registration_id", "mailing_address",
                   "expected_registration_version")
    reg = db.registrations.get(body["registration_id"])
    if reg is None:
        raise not_found("Registration not found.")

    if not isinstance(body["mailing_address"], str) or not body["mailing_address"].strip():
        raise invalid_request("mailing_address must be a non-empty string.")
    ev = body["expected_registration_version"]
    if isinstance(ev, bool) or not isinstance(ev, int):
        raise invalid_request("expected_registration_version must be an integer.")

    # State (priority 11): registration must be ACTIVE.
    if reg["status"] != "ACTIVE":
        raise APIError(E.ERR_REGISTRATION_NOT_ACTIVE,
                       "Registration is not ACTIVE.", 409)

    # Temporal window (priority 6): before absentee_request_deadline.
    election = db.elections.get(reg["election_id"])
    if clock_now() >= parse_iso(election["absentee_request_deadline"]):
        raise APIError(E.ERR_WINDOW_CLOSED,
                       "Absentee request deadline has passed.", 422)

    # OCC (priority 19): expected_registration_version must match live version.
    if ev != reg["version"]:
        raise stale_version("Registration version is stale.")

    row = {
        "registration_id": reg["id"],
        "election_id": reg["election_id"],
        "precinct_id": reg.get("precinct_id"),
        "mailing_address": body["mailing_address"],
        "request_status": "REQUESTED",
        "cure_status": "NONE",
        "returned_at": None,
    }
    db.stamp_create_full(row)
    db.ballots[row["id"]] = row

    # Creating the ballot advances the parent registration's version (§2.8).
    db.stamp_update(reg)
    return ok_object(serialize.ballot_view(row), 201)


@bp.route("/absentee-ballots/<bid>", methods=["GET"])
def get_ballot(bid):
    require_roles("ElectionAdmin", "ElectionOfficial", "Voter")
    b = db.ballots.get(bid)
    if b is None:
        raise not_found("Absentee ballot not found.")
    return ok_object(serialize.ballot_view(b))


@bp.route("/absentee-ballots", methods=["GET"])
def list_ballots():
    require_roles("ElectionAdmin", "ElectionOfficial")
    reg_id = request.args.get("registration_id")
    election_id = request.args.get("election_id")
    precinct_id = request.args.get("precinct_id")
    request_status = request.args.get("request_status")
    cure_status = request.args.get("cure_status")
    rows = list(db.ballots.values())
    if reg_id is not None:
        rows = [r for r in rows if r["registration_id"] == reg_id]
    if election_id is not None:
        rows = [r for r in rows if r.get("election_id") == election_id]
    if precinct_id is not None:
        rows = [r for r in rows if r.get("precinct_id") == precinct_id]
    if request_status is not None:
        rows = [r for r in rows if r["request_status"] == request_status]
    if cure_status is not None:
        rows = [r for r in rows if r["cure_status"] == cure_status]
    page, limit, offset, total, has_more = paginate(rows)
    return ok_array([serialize.ballot_view(r) for r in page],
                    limit=limit, offset=offset, total_count=total, has_more=has_more)


@bp.route("/absentee-ballots/<bid>/transition", methods=["POST"])
def transition_ballot(bid):
    require_roles("ElectionOfficial")
    b = db.ballots.get(bid)
    if b is None:
        raise not_found("Absentee ballot not found.")
    body = get_json_body()
    require_fields(body, "target_request_status")
    target = body["target_request_status"]
    if target not in REQUEST_TARGETS:
        raise invalid_request("Unknown target_request_status.")

    cur = b["request_status"]
    reg = db.registrations.get(b["registration_id"])
    election = db.elections.get(b.get("election_id"))

    if target == "ISSUED":
        if cur != "REQUESTED":
            raise invalid_state("Ballot is not REQUESTED.")
        if reg is None or reg["status"] != "ACTIVE":
            raise invalid_state("Linked registration is not ACTIVE.")
        b["request_status"] = "ISSUED"
        db.stamp_update(b)
        return ok_object(serialize.ballot_view(b))

    if target == "RETURNED":
        if cur != "ISSUED":
            raise invalid_state("Ballot is not ISSUED.")
        if clock_now() >= parse_iso(election["election_date"]):
            raise APIError(E.ERR_WINDOW_CLOSED,
                           "Cannot return a ballot at or after election_date.", 422)
        b["request_status"] = "RETURNED"
        b["returned_at"] = db.current_utc_iso()
        db.stamp_update(b)
        return ok_object(serialize.ballot_view(b))

    if target == "ACCEPTED":
        if cur != "RETURNED":
            raise invalid_state("Ballot is not RETURNED.")
        if b["cure_status"] not in ("NONE", "CURED"):
            raise APIError(E.ERR_BALLOT_NOT_CURED,
                           "Ballot cure status blocks acceptance.", 409)
        b["request_status"] = "ACCEPTED"
        db.stamp_update(b)
        if election is not None:
            recompute_election_counts(election)
            db.stamp_update(election)
        return ok_object(serialize.ballot_view(b))

    raise invalid_request("Unsupported target_request_status.")


@bp.route("/absentee-ballots/<bid>/flag-cure", methods=["POST"])
def flag_cure(bid):
    require_roles("ElectionOfficial")
    b = db.ballots.get(bid)
    if b is None:
        raise not_found("Absentee ballot not found.")
    body = get_json_body()
    require_fields(body, "reason")
    if body["reason"] not in CURE_REASONS:
        raise invalid_request("reason out of range.")

    # State: request_status==RETURNED and cure_status==NONE.
    if b["request_status"] != "RETURNED" or b["cure_status"] != "NONE":
        raise invalid_state("Ballot cannot be flagged in its current state.")

    # Open a cure case (cross-aggregate cascade).
    case = {
        "ballot_id": b["id"],
        "election_id": b.get("election_id"),
        "reason": body["reason"],
        "voter_response_text": None,
        "status": "OPEN",
        "adjudicated_by_user_id": None,
    }
    db.stamp_create_full(case)
    db.cure_cases[case["id"]] = case

    b["cure_status"] = "FLAGGED"
    db.stamp_update(b)
    return ok_object(serialize.ballot_view(b))
