"""Voting-machine endpoints."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import current_user, require_roles
from ..envelope import success_object
from ..errors import (
    err_bad_request,
    err_forbidden,
    err_invalid_state,
)
from ..serializers import serialize_voting_machine
from ..services.common import bump_version, check_version, require
from ..store import store
from ..util import new_uuid
from ._helpers import as_str, get_json_body, get_version, require_field

bp = Blueprint("machines", __name__)

FAILURE_REASONS = {"POWER", "JAM", "TAMPER", "OTHER"}


@bp.route(
    "/elections/<election_id>/precincts/<precinct_id>/voting-machines",
    methods=["POST"],
)
@require_roles(["ElectionBoard"])
def create_machine(election_id: str, precinct_id: str):
    require("elections", election_id)
    p = require("precincts", precinct_id)
    if p["election_id"] != election_id:
        from ..errors import err_not_found
        raise err_not_found()

    body = get_json_body()
    serial_no = as_str(require_field(body, "serial_no"), "serial_no")

    s = store()
    # Globally unique serial_no
    for m in s.voting_machines.values():
        if m.get("serial_no") == serial_no:
            raise err_invalid_state("serial_no already in use")

    now = s.now()
    m = {
        "id": new_uuid(),
        "precinct_id": precinct_id,
        "serial_no": serial_no,
        "status": "READY",
        "failure_reason": None,
        "down_since": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    s.insert("voting_machines", m)
    return jsonify(success_object(serialize_voting_machine(m))), 201


@bp.route("/voting-machines/<machine_id>", methods=["GET"])
@require_roles(["ElectionBoard", "PrecinctOfficer"])
def get_machine(machine_id: str):
    m = require("voting_machines", machine_id)
    return jsonify(success_object(serialize_voting_machine(m))), 200


@bp.route("/voting-machines/<machine_id>/state", methods=["POST"])
@require_roles(["PrecinctOfficer", "ElectionBoard"])
def machine_transition(machine_id: str):
    m = require("voting_machines", machine_id)
    body = get_json_body()
    to_state = as_str(require_field(body, "to_state"), "to_state")
    failure_reason = body.get("failure_reason")
    version = get_version(body)

    s = store()
    now = s.now()
    precinct = require("precincts", m["precinct_id"])
    election = require("elections", precinct["election_id"])
    from_state = m["status"]
    uid, role = current_user()

    legal = {
        ("IN_USE", "DOWN"),
        ("READY", "DOWN"),  # accommodate the concurrency rule where a READY machine may also be downed
        ("DOWN", "READY"),
        ("READY", "DECOMMISSIONED"),
    }
    if (from_state, to_state) not in legal:
        raise err_invalid_state(f"Machine cannot transition {from_state} -> {to_state}")

    if to_state == "DOWN":
        if failure_reason is None:
            raise err_bad_request("failure_reason is required for DOWN")
        if failure_reason not in FAILURE_REASONS:
            raise err_bad_request("failure_reason must be POWER|JAM|TAMPER|OTHER")
        if election["state"] != "ELECTION_DAY":
            raise err_invalid_state("Election must be ELECTION_DAY")
        check_version(m, version)
        m["status"] = "DOWN"
        m["failure_reason"] = failure_reason
        m["down_since"] = now
        bump_version(m, now)

    elif to_state == "READY":
        check_version(m, version)
        m["status"] = "READY"
        m["failure_reason"] = None
        bump_version(m, now)

    elif to_state == "DECOMMISSIONED":
        if role != "ElectionBoard":
            raise err_forbidden("Only ElectionBoard may DECOMMISSION")
        if election["state"] != "CERTIFIED":
            raise err_invalid_state("Election must be CERTIFIED to DECOMMISSION")
        check_version(m, version)
        m["status"] = "DECOMMISSIONED"
        bump_version(m, now)

    return jsonify(success_object(serialize_voting_machine(m))), 200
