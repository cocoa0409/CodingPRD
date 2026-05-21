"""Recount-request endpoints."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import require_roles
from ..envelope import paginate, parse_pagination, success_array, success_object
from ..errors import (
    err_bad_request,
    err_deadline_passed,
    err_invalid_state,
    err_recount_no_overturn,
    err_recount_petition_insufficient,
    err_recount_required,
)
from ..serializers import serialize_recount
from ..services.common import bump_version, check_version, require
from ..services.tally import election_totals, election_winner
from ..store import store
from ..util import new_uuid
from ._helpers import as_str, get_json_body, get_version, require_field

bp = Blueprint("recounts", __name__)


@bp.route("/elections/<election_id>/recounts", methods=["POST"])
@require_roles(["ElectionBoard"])
def create_recount(election_id: str):
    election = require("elections", election_id)
    body = get_json_body()
    petition_count = require_field(body, "petition_count")
    if not isinstance(petition_count, int) or isinstance(petition_count, bool):
        raise err_bad_request("petition_count must be an integer")
    # Manual petition threshold
    if petition_count < 100:
        raise err_recount_petition_insufficient()

    s = store()
    now = s.now()
    rr = {
        "id": new_uuid(),
        "election_id": election_id,
        "requested_by_role": "ElectionBoard",
        "petition_count": petition_count,
        "trigger_margin_pct": None,
        "status": "REQUESTED",
        "reconciled_totals_json": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    s.insert("recount_requests", rr)
    return jsonify(success_object(serialize_recount(rr))), 201


@bp.route("/elections/<election_id>/recounts", methods=["GET"])
@require_roles(["ElectionBoard"])
def list_recounts(election_id: str):
    require("elections", election_id)
    s = store()
    limit, offset = parse_pagination()
    items = [
        s.recount_requests[i]
        for i in s.insertion_order["recount_requests"]
        if s.recount_requests[i]["election_id"] == election_id
    ]
    total = len(items)
    page = paginate(items, limit, offset)
    return (
        jsonify(
            success_array(
                [serialize_recount(r) for r in page],
                limit=limit, offset=offset, total_count=total,
            )
        ),
        200,
    )


@bp.route("/recounts/<recount_id>/state", methods=["POST"])
@require_roles(["ElectionBoard"])
def recount_transition(recount_id: str):
    rr = require("recount_requests", recount_id)
    body = get_json_body()
    to_state = as_str(require_field(body, "to_state"), "to_state")
    version = get_version(body)

    s = store()
    election = require("elections", rr["election_id"])
    now = s.now()
    from_state = rr["status"]

    legal = {
        ("REQUESTED", "APPROVED"),
        ("REQUESTED", "DENIED"),
        ("APPROVED", "IN_PROGRESS"),
        ("IN_PROGRESS", "RESOLVED_NO_CHANGE"),
        ("IN_PROGRESS", "RESOLVED_OVERTURN"),
    }
    if (from_state, to_state) not in legal:
        raise err_invalid_state(f"RecountRequest cannot transition {from_state} -> {to_state}")

    if to_state == "APPROVED":
        if rr["requested_by_role"] == "ElectionBoard" and rr.get("petition_count", 0) < 100:
            raise err_recount_petition_insufficient()
        if election["state"] not in ("TALLY", "RECOUNT"):
            raise err_invalid_state("Election must be TALLY or RECOUNT to approve recount")
        check_version(rr, version)
        rr["status"] = "APPROVED"
        bump_version(rr, now)

    elif to_state == "DENIED":
        if rr["requested_by_role"] == "system":
            raise err_recount_required()
        check_version(rr, version)
        rr["status"] = "DENIED"
        bump_version(rr, now)

    elif to_state == "IN_PROGRESS":
        check_version(rr, version)
        rr["status"] = "IN_PROGRESS"
        bump_version(rr, now)
        # Cascade-up: election TALLY -> RECOUNT
        if election["state"] == "TALLY":
            election["state"] = "RECOUNT"
            bump_version(election, now)
        # cascade-down: all TALLIED ballots -> CHALLENGED with RECOUNT_DISCREPANCY
        for b in s.ballot_casts.values():
            if b.get("election_id") == election["id"] and b.get("status") == "TALLIED":
                b["status"] = "CHALLENGED"
                b["challenge_reason"] = "RECOUNT_DISCREPANCY"
                bump_version(b, now)

    elif to_state in ("RESOLVED_NO_CHANGE", "RESOLVED_OVERTURN"):
        provisional_winner = election_winner(election["id"], "provisional")
        reconciled_winner = election_winner(election["id"], "reconciled")
        if to_state == "RESOLVED_NO_CHANGE":
            if reconciled_winner != provisional_winner:
                # Allow noting reality? PRD says NO_CHANGE means winners agree;
                # if reconciled winner differs, NO_CHANGE is invalid.
                # Treat as invalid state.
                raise err_invalid_state("Reconciled winner differs; use RESOLVED_OVERTURN")
        else:  # RESOLVED_OVERTURN
            if reconciled_winner == provisional_winner:
                raise err_recount_no_overturn()
        check_version(rr, version)
        rr["status"] = to_state
        rr["reconciled_totals_json"] = election_totals(election["id"], "reconciled")
        bump_version(rr, now)
        # Cascade-down: every CHALLENGED ballot -> TALLIED, clear challenge_reason
        for b in s.ballot_casts.values():
            if b.get("election_id") == election["id"] and b.get("status") == "CHALLENGED":
                b["status"] = "TALLIED"
                b["challenge_reason"] = None
                bump_version(b, now)

    return jsonify(success_object(serialize_recount(rr))), 200
