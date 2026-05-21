"""Election endpoints."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import current_user, require_roles
from ..envelope import paginate, parse_pagination, success_array, success_object
from ..errors import (
    err_bad_request,
    err_curing_in_progress,
    err_deadline_passed,
    err_invalid_state,
    err_no_precincts,
    err_recount_required,
    err_tally_too_early,
)
from ..serializers import serialize_election
from ..services.common import bump_version, check_version, require
from ..services.tally import (
    election_margin,
    election_totals,
    election_winner,
    precinct_breakdown,
)
from ..store import store
from ..util import new_uuid, parse_iso8601
from ._helpers import get_json_body, get_version, require_field, as_str

bp = Blueprint("elections", __name__)

VIEW_ROLES = ["ElectionBoard", "RegistrarClerk", "ReviewerClerk", "PrecinctOfficer", "Voter"]


def _parse_dt(body: dict, key: str):
    raw = require_field(body, key)
    try:
        return parse_iso8601(raw)
    except Exception:
        raise err_bad_request(f"'{key}' must be ISO 8601")


@bp.route("/elections", methods=["POST"])
@require_roles(["ElectionBoard"])
def create_election():
    body = get_json_body()
    name = as_str(require_field(body, "name"), "name")
    election_date = _parse_dt(body, "election_date")
    registration_deadline = _parse_dt(body, "registration_deadline")
    absentee_request_deadline = _parse_dt(body, "absentee_request_deadline")
    early_voting_starts_at = _parse_dt(body, "early_voting_starts_at")
    early_voting_ends_at = _parse_dt(body, "early_voting_ends_at")
    ballot_return_deadline = _parse_dt(body, "ballot_return_deadline")
    cure_deadline = _parse_dt(body, "cure_deadline")
    certification_deadline = _parse_dt(body, "certification_deadline")
    recount_threshold_pct = body.get("recount_threshold_pct", 0.005)
    if not isinstance(recount_threshold_pct, (int, float)) or isinstance(recount_threshold_pct, bool):
        raise err_bad_request("recount_threshold_pct must be a number")

    s = store()
    now = s.now()
    e = {
        "id": new_uuid(),
        "name": name,
        "election_date": election_date,
        "registration_deadline": registration_deadline,
        "absentee_request_deadline": absentee_request_deadline,
        "early_voting_starts_at": early_voting_starts_at,
        "early_voting_ends_at": early_voting_ends_at,
        "ballot_return_deadline": ballot_return_deadline,
        "cure_deadline": cure_deadline,
        "certification_deadline": certification_deadline,
        "recount_threshold_pct": float(recount_threshold_pct),
        "state": "DRAFT",
        "certified_winner_voter_choice": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    s.insert("elections", e)
    return jsonify(success_object(serialize_election(e))), 201


@bp.route("/elections/<election_id>", methods=["GET"])
@require_roles(VIEW_ROLES)
def get_election(election_id: str):
    e = require("elections", election_id)
    return jsonify(success_object(serialize_election(e))), 200


@bp.route("/elections", methods=["GET"])
@require_roles(VIEW_ROLES)
def list_elections():
    s = store()
    limit, offset = parse_pagination()
    state_filter = request.args.get("state")
    items = [s.elections[i] for i in s.insertion_order["elections"]]
    if state_filter:
        items = [e for e in items if e["state"] == state_filter]
    total = len(items)
    page = paginate(items, limit, offset)
    body = success_array(
        [serialize_election(e) for e in page],
        limit=limit,
        offset=offset,
        total_count=total,
    )
    return jsonify(body), 200


@bp.route("/elections/<election_id>/state", methods=["POST"])
@require_roles(["ElectionBoard"])
def election_transition(election_id: str):
    body = get_json_body()
    to_state = as_str(require_field(body, "to_state"), "to_state")
    version = get_version(body)

    s = store()
    now = s.now()
    e = require("elections", election_id)

    # priority order: state legality first, then deadline/business, then OCC
    from_state = e["state"]
    legal = {
        ("DRAFT", "OPEN_REGISTRATION"),
        ("ELECTION_DAY", "TALLY"),
        ("TALLY", "CERTIFIED"),
        ("RECOUNT", "CERTIFIED"),
    }
    if (from_state, to_state) not in legal:
        raise err_invalid_state(f"Cannot transition Election {from_state} -> {to_state}")

    if from_state == "DRAFT" and to_state == "OPEN_REGISTRATION":
        # PRD §3.1: precinct existence is the named precondition.
        # SCAFFOLD lists deadline first; we evaluate state-machine
        # preconditions in scaffold order: deadline before precinct check.
        if now > e["registration_deadline"]:
            raise err_deadline_passed("registration_deadline has passed")
        has_precinct = any(p.get("election_id") == election_id for p in s.precincts.values())
        if not has_precinct:
            raise err_no_precincts()
        check_version(e, version)
        e["state"] = "OPEN_REGISTRATION"
        bump_version(e, now)

    elif from_state == "ELECTION_DAY" and to_state == "TALLY":
        if now < e["ballot_return_deadline"]:
            raise err_tally_too_early()
        # No CuringCase still open
        for cc in s.curing_cases.values():
            if cc.get("election_id") == election_id and cc.get("status") in (
                "OPEN_PENDING_VOTER",
                "UNDER_REVIEW",
            ):
                raise err_curing_in_progress()
        check_version(e, version)
        e["state"] = "TALLY"
        bump_version(e, now)
        # Side effects: tally all CAST ballots to TALLIED, compute margin,
        # auto-create RecountRequest if threshold met.
        for b in s.ballot_casts.values():
            if b.get("election_id") == election_id and b.get("status") == "CAST":
                b["status"] = "TALLIED"
                bump_version(b, now)
        margin = election_margin(election_id, "provisional")
        if margin <= e["recount_threshold_pct"]:
            rr = {
                "id": new_uuid(),
                "election_id": election_id,
                "requested_by_role": "system",
                "petition_count": 0,
                "trigger_margin_pct": margin,
                "status": "REQUESTED",
                "reconciled_totals_json": None,
                "created_at": now,
                "updated_at": now,
                "version": 1,
            }
            s.insert("recount_requests", rr)

    elif from_state == "TALLY" and to_state == "CERTIFIED":
        # Recount-required check
        margin = election_margin(election_id, "provisional")
        if margin <= e["recount_threshold_pct"]:
            raise err_recount_required()
        # No CuringCase still open
        for cc in s.curing_cases.values():
            if cc.get("election_id") == election_id and cc.get("status") in (
                "OPEN_PENDING_VOTER",
                "UNDER_REVIEW",
            ):
                raise err_curing_in_progress()
        if now > e["certification_deadline"]:
            raise err_deadline_passed("certification_deadline has passed")
        check_version(e, version)
        e["state"] = "CERTIFIED"
        e["certified_winner_voter_choice"] = election_winner(election_id, "provisional")
        bump_version(e, now)

    elif from_state == "RECOUNT" and to_state == "CERTIFIED":
        # All recount requests for this election must be resolved
        terminal = {"RESOLVED_NO_CHANGE", "RESOLVED_OVERTURN", "DENIED"}
        for rr in s.recount_requests.values():
            if rr.get("election_id") == election_id and rr.get("status") not in terminal:
                raise err_invalid_state("Some recount requests are not resolved")
        if now > e["certification_deadline"]:
            raise err_deadline_passed("certification_deadline has passed")
        check_version(e, version)
        e["state"] = "CERTIFIED"
        # Use winner from the most recent resolved recount (reconciled),
        # fall back to provisional otherwise.
        e["certified_winner_voter_choice"] = election_winner(election_id, "reconciled")
        bump_version(e, now)

    return jsonify(success_object(serialize_election(e))), 200


@bp.route("/elections/<election_id>/tally", methods=["GET"])
@require_roles(["ElectionBoard", "RegistrarClerk"])
def get_tally(election_id: str):
    e = require("elections", election_id)
    variant = request.args.get("variant", "provisional").lower()
    if variant not in ("provisional", "reconciled"):
        raise err_bad_request("variant must be provisional or reconciled")
    payload = {
        "election_id": election_id,
        "variant": variant,
        "election_totals": election_totals(election_id, variant),
        "election_margin_pct": election_margin(election_id, variant),
        "winner_voter_choice": election_winner(election_id, variant),
        "per_precinct": precinct_breakdown(election_id, variant),
    }
    return jsonify(success_object(payload)), 200
