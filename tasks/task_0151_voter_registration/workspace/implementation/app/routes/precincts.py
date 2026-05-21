"""Precinct endpoints."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import require_roles
from ..envelope import paginate, parse_pagination, success_array, success_object
from ..errors import err_bad_request, err_invalid_state
from ..serializers import serialize_precinct
from ..services.common import require
from ..store import store
from ..util import new_uuid
from ._helpers import as_str, get_json_body, require_field

bp = Blueprint("precincts", __name__)


@bp.route("/elections/<election_id>/precincts", methods=["POST"])
@require_roles(["ElectionBoard"])
def create_precinct(election_id: str):
    election = require("elections", election_id)
    body = get_json_body()
    code = as_str(require_field(body, "code"), "code")
    street_pattern = as_str(require_field(body, "street_pattern"), "street_pattern")
    capacity_machines = require_field(body, "capacity_machines")
    if not isinstance(capacity_machines, int) or isinstance(capacity_machines, bool):
        raise err_bad_request("capacity_machines must be an integer")
    if capacity_machines < 0:
        raise err_bad_request("capacity_machines must be >= 0")

    s = store()
    # Unique (election_id, code)
    for p in s.precincts.values():
        if p["election_id"] == election_id and p["code"] == code:
            raise err_invalid_state("Precinct code already exists in this election")

    now = s.now()
    p = {
        "id": new_uuid(),
        "election_id": election_id,
        "code": code,
        "street_pattern": street_pattern,
        "capacity_machines": capacity_machines,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    s.insert("precincts", p)
    return jsonify(success_object(serialize_precinct(p))), 201


@bp.route("/elections/<election_id>/precincts/<precinct_id>", methods=["GET"])
@require_roles(["ElectionBoard", "RegistrarClerk", "PrecinctOfficer"])
def get_precinct(election_id: str, precinct_id: str):
    require("elections", election_id)
    p = require("precincts", precinct_id)
    if p["election_id"] != election_id:
        # Nested ownership: precinct must belong to this election
        from ..errors import err_not_found
        raise err_not_found()
    return jsonify(success_object(serialize_precinct(p))), 200


@bp.route("/elections/<election_id>/precincts", methods=["GET"])
@require_roles(["ElectionBoard", "RegistrarClerk", "PrecinctOfficer"])
def list_precincts(election_id: str):
    require("elections", election_id)
    s = store()
    limit, offset = parse_pagination()
    items = [s.precincts[i] for i in s.insertion_order["precincts"] if s.precincts[i]["election_id"] == election_id]
    total = len(items)
    page = paginate(items, limit, offset)
    return (
        jsonify(success_array([serialize_precinct(p) for p in page], limit=limit, offset=offset, total_count=total)),
        200,
    )
