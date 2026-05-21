"""Voter endpoints (creation, patch, state transitions, party registration)."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import current_user, require_roles
from ..envelope import paginate, parse_pagination, success_array, success_object
from ..errors import (
    err_bad_request,
    err_deadline_passed,
    err_forbidden,
    err_invalid_state,
    err_no_precinct_match,
    err_party_locked,
    err_voter_has_ballot,
)
from ..serializers import serialize_party_registration, serialize_voter
from ..services.cascades import cascade_voter_suspend
from ..services.common import bump_version, check_version, require
from ..services.eligibility import (
    ELIGIBLE_AGE,
    MIN_RESIDENCY_DAYS,
    check_strict_eligibility,
    in_cure_grace_window,
)
from ..services.precinct_assignment import assign_precinct
from ..store import store
from ..util import new_uuid, parse_iso8601
from ._helpers import as_str, get_json_body, get_version, require_field

bp = Blueprint("voters", __name__)


def _parse_dt(body: dict, key: str):
    raw = require_field(body, key)
    try:
        return parse_iso8601(raw)
    except Exception:
        raise err_bad_request(f"'{key}' must be ISO 8601")


def _voter_self_only(voter: dict) -> None:
    """Voter role can only act on their own row."""
    uid, role = current_user()
    if role == "Voter" and voter["id"] != uid:
        raise err_forbidden("Voter can only act on their own row")


# ---------------- POST /voters ----------------
@bp.route("/voters", methods=["POST"])
@require_roles(["RegistrarClerk", "Voter"])
def create_voter():
    body = get_json_body()
    full_name = as_str(require_field(body, "full_name"), "full_name")
    dob = _parse_dt(body, "date_of_birth")
    residency_address = as_str(require_field(body, "residency_address"), "residency_address")
    residency_since = _parse_dt(body, "residency_since")
    is_citizen = require_field(body, "is_citizen")
    if not isinstance(is_citizen, bool):
        raise err_bad_request("'is_citizen' must be a boolean")
    election_id = as_str(require_field(body, "election_id"), "election_id")

    s = store()
    require("elections", election_id)
    now = s.now()
    v = {
        "id": new_uuid(),
        "full_name": full_name,
        "date_of_birth": dob,
        "residency_address": residency_address,
        "residency_since": residency_since,
        "is_citizen": is_citizen,
        "election_id": election_id,
        "precinct_id": None,
        "status": "PENDING",
        "party_affiliation": "UNAFFILIATED",
        "party_locked_at": None,
        "registered_by_user_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    v["precinct_id"] = assign_precinct(v)
    s.insert("voters", v)
    return jsonify(success_object(serialize_voter(v))), 201


@bp.route("/voters/<voter_id>", methods=["GET"])
@require_roles(["RegistrarClerk", "ReviewerClerk", "Voter", "ElectionBoard"])
def get_voter(voter_id: str):
    v = require("voters", voter_id)
    uid, role = current_user()
    if role == "Voter" and v["id"] != uid:
        raise err_forbidden("Voter can only view their own row")
    return jsonify(success_object(serialize_voter(v))), 200


# ---------------- PATCH /voters/{id} ----------------
@bp.route("/voters/<voter_id>", methods=["PATCH"])
@require_roles(["RegistrarClerk", "Voter"])
def patch_voter(voter_id: str):
    v = require("voters", voter_id)
    _voter_self_only(v)
    body = get_json_body()
    version = get_version(body)
    check_version(v, version)

    s = store()
    now = s.now()
    changed = False

    if "full_name" in body:
        v["full_name"] = as_str(body["full_name"], "full_name")
        changed = True
    if "residency_since" in body:
        try:
            v["residency_since"] = parse_iso8601(body["residency_since"])
        except Exception:
            raise err_bad_request("'residency_since' must be ISO 8601")
        changed = True
    if "residency_address" in body:
        v["residency_address"] = as_str(body["residency_address"], "residency_address")
        # Re-run precinct assignment
        v["precinct_id"] = assign_precinct(v)
        changed = True

    if changed:
        bump_version(v, now)
    return jsonify(success_object(serialize_voter(v))), 200


# ---------------- POST /voters/{id}/state ----------------
@bp.route("/voters/<voter_id>/state", methods=["POST"])
@require_roles(["RegistrarClerk"])
def voter_transition(voter_id: str):
    v = require("voters", voter_id)
    body = get_json_body()
    to_state = as_str(require_field(body, "to_state"), "to_state")
    version = get_version(body)

    s = store()
    election = require("elections", v["election_id"])
    now = s.now()
    from_state = v["status"]
    uid, _role = current_user()

    legal = {
        ("PENDING", "ACTIVE"),
        ("ACTIVE", "SUSPENDED"),
        ("SUSPENDED", "ACTIVE"),
        ("ACTIVE", "PURGED"),
        ("SUSPENDED", "PURGED"),
    }
    if (from_state, to_state) not in legal:
        raise err_invalid_state(f"Voter cannot transition {from_state} -> {to_state}")

    if to_state == "ACTIVE" and from_state == "PENDING":
        # Strict eligibility enforced (raises ERR_NOT_CITIZEN | UNDER_AGE |
        # RESIDENCY_INSUFFICIENT | DEADLINE_PASSED | NO_PRECINCT_MATCH)
        check_strict_eligibility(v, election)
        check_version(v, version)
        v["status"] = "ACTIVE"
        v["party_locked_at"] = election["registration_deadline"]
        v["registered_by_user_id"] = uid
        bump_version(v, now)

    elif to_state == "SUSPENDED":
        # Cannot suspend a voter who has cast a (still-counting) ballot
        for b in s.ballot_casts.values():
            if b.get("voter_id") == voter_id and b.get("election_id") == election["id"]:
                if b.get("status") in ("CAST", "TALLIED"):
                    raise err_voter_has_ballot()
        check_version(v, version)
        v["status"] = "SUSPENDED"
        bump_version(v, now)
        cascade_voter_suspend(v)

    elif to_state == "ACTIVE" and from_state == "SUSPENDED":
        # PRD §3.6: cure-grace variant — when election is EARLY_VOTING,
        # now is within 7 days of registration_deadline, and the voter
        # was ACTIVE at the moment of registration_deadline, residency
        # AND the deadline check are waived; citizenship + age + precinct
        # still hold.
        if (
            in_cure_grace_window(election)
            and v.get("was_active_at_registration_deadline")
        ):
            if not v.get("is_citizen", False):
                from ..errors import err_not_citizen
                raise err_not_citizen()
            from datetime import timedelta as _td
            # age via the same formula as strict
            from ..services.eligibility import _age_years
            if _age_years(v, election) < ELIGIBLE_AGE:
                from ..errors import err_under_age
                raise err_under_age()
            if v.get("precinct_id") is None:
                raise err_no_precinct_match()
        else:
            if now > election["registration_deadline"]:
                raise err_deadline_passed("registration_deadline has passed")
            check_strict_eligibility(v, election)
        check_version(v, version)
        v["status"] = "ACTIVE"
        bump_version(v, now)

    elif to_state == "PURGED":
        if election["state"] != "CERTIFIED":
            raise err_invalid_state("Election must be CERTIFIED before purging voters")
        check_version(v, version)
        v["status"] = "PURGED"
        bump_version(v, now)

    return jsonify(success_object(serialize_voter(v))), 200


# ---------------- POST /voters/{id}/party-registration ----------------
@bp.route("/voters/<voter_id>/party-registration", methods=["POST"])
@require_roles(["Voter", "RegistrarClerk"])
def change_party(voter_id: str):
    v = require("voters", voter_id)
    _voter_self_only(v)
    body = get_json_body()
    new_party = as_str(require_field(body, "new_party"), "new_party")
    version = get_version(body)
    if new_party not in {"DEMOCRATIC", "REPUBLICAN", "INDEPENDENT", "UNAFFILIATED"}:
        raise err_bad_request("new_party must be a valid party value")

    s = store()
    election = require("elections", v["election_id"])
    now = s.now()
    locked_at = v.get("party_locked_at") or election.get("registration_deadline")
    if locked_at is not None and now >= locked_at:
        raise err_party_locked()
    check_version(v, version)

    uid, role = current_user()
    actor_role = "VoterSelf" if role == "Voter" else "RegistrarClerk"
    previous = v.get("party_affiliation", "UNAFFILIATED")

    pr = {
        "id": new_uuid(),
        "voter_id": voter_id,
        "previous_party": previous,
        "new_party": new_party,
        "actor_role": actor_role,
        "created_at": now,
    }
    s.insert("party_registrations", pr)
    v["party_affiliation"] = new_party
    bump_version(v, now)
    return jsonify(success_object(serialize_party_registration(pr))), 201


@bp.route("/voters/<voter_id>/party-registration", methods=["GET"])
@require_roles(["Voter", "RegistrarClerk", "ElectionBoard"])
def list_party_history(voter_id: str):
    v = require("voters", voter_id)
    uid, role = current_user()
    if role == "Voter" and v["id"] != uid:
        raise err_forbidden("Voter can only view their own row")
    s = store()
    limit, offset = parse_pagination()
    items = [
        s.party_registrations[i] for i in s.insertion_order["party_registrations"]
        if s.party_registrations[i]["voter_id"] == voter_id
    ]
    total = len(items)
    page = paginate(items, limit, offset)
    return (
        jsonify(
            success_array(
                [serialize_party_registration(p) for p in page],
                limit=limit, offset=offset, total_count=total,
            )
        ),
        200,
    )
