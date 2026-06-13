"""Unit routes (PRD §3.5)."""
from flask import Blueprint, request

import db
import errors
import response
from middleware import authenticate, require_role, get_json
from services.common import (
    make_common, public, lookup,
    as_number, as_string, parse_pagination, paginate,
)
from services import ledger

bp = Blueprint("units", __name__)

READ_ROLES = {"RmaAdmin", "Agent", "LossAdjuster"}


@bp.post("/units")
def create_unit():
    _, role = authenticate()
    require_role(role, {"Agent"})
    body = get_json()
    coverage_election_id = as_string(body, "coverage_election_id")
    unit_number = as_string(body, "unit_number")
    acres = as_number(body, "acres")
    share = as_number(body, "share")
    if acres <= 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "acres must be > 0")
    if not (0 < share <= 1):
        raise errors.err(errors.ERR_INVALID_REQUEST, "share must be > 0 and <= 1")

    election = lookup(db.coverage_elections, coverage_election_id)

    entity = make_common()
    entity.update({
        "coverage_election_id": coverage_election_id,
        "unit_number": unit_number,
        "acres": acres,
        "share": share,
        "planted_acres": 0,
        "prevented_acres": 0,
        "status": "PENDING",
    })
    db.units[entity["id"]] = entity

    # Recompute election premium + subsidy split, then owning policy ledger (PRD §3.5)
    ledger.recompute_election_premium(election, bump=True)
    policy = ledger.policy_of_election(election)
    if policy is not None:
        ledger.recompute_policy_premium(policy, bump=True)

    return response.success_object(public(entity), 201)


@bp.get("/units/<uid>")
def get_unit(uid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    entity = lookup(db.units, uid)
    return response.success_object(public(entity), 200)


@bp.get("/units")
def list_units():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    items = list(db.units.values())
    if "coverage_election_id" in request.args:
        items = [u for u in items if u["coverage_election_id"] == request.args.get("coverage_election_id")]
    page, total = paginate(items, limit, offset)
    return response.success_array(page, limit, offset, total, 200)


@bp.get("/units/<uid>/acreage-reports")
def list_unit_reports(uid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    lookup(db.units, uid)
    limit, offset = parse_pagination()
    items = ledger.reports_of_unit(uid)
    page, total = paginate(items, limit, offset)
    return response.success_array(page, limit, offset, total, 200)
