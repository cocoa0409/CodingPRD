"""AcreageReport routes (PRD §3.5)."""
from flask import Blueprint, request

import db
import errors
import response
from middleware import authenticate, require_role, get_json
from services.common import (
    make_common, public, touch, lookup,
    as_number, as_int, as_string, parse_datetime, parse_iso,
    parse_pagination, paginate,
)
from services import ledger
from services import transitions

bp = Blueprint("acreage_reports", __name__)

READ_ROLES = {"RmaAdmin", "Agent", "LossAdjuster"}


@bp.post("/acreage-reports")
def create_report():
    _, role = authenticate()
    require_role(role, {"Agent"})
    body = get_json()

    unit_id = as_string(body, "unit_id")
    planted_acres = as_number(body, "planted_acres")
    prevented_acres = as_number(body, "prevented_acres")
    if planted_acres < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "planted_acres must be >= 0")
    if prevented_acres < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "prevented_acres must be >= 0")
    planting_date = parse_datetime(body, "planting_date", required=False)
    expected_unit_version = as_int(body, "expected_unit_version")

    # FK existence (priority 3)
    unit = lookup(db.units, unit_id)

    # OCC (priority 5)
    if expected_unit_version != unit["version"]:
        raise errors.err(errors.ERR_STALE_VERSION,
                         "expected_unit_version does not match the unit's current version")

    # State check (priority 6): owning election must be ELECTED for the report to
    # move the unit forward (PRD §3.5; state machine PENDING->REPORTED precondition)
    election = ledger.election_of_unit(unit)
    if election is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Owning election not found")
    if election["status"] != "ELECTED":
        raise errors.err(errors.ERR_INVALID_STATE,
                         "Owning coverage election is not in ELECTED status")

    program = ledger.program_of_election(election)

    # Business temporal (priority 11): deadline gate (PRD §3.5)
    deadline = parse_iso(program["acreage_reporting_deadline"], "acreage_reporting_deadline")
    if db.server_now() > deadline:
        raise errors.err(errors.ERR_ACREAGE_DEADLINE_PASSED,
                         "Acreage reporting deadline has passed")

    # Business constraint (priority 12): planted + prevented <= unit.acres
    if planted_acres + prevented_acres > unit["acres"]:
        raise errors.err(errors.ERR_ACREAGE_OVER_REPORTED,
                         "planted_acres + prevented_acres exceeds the unit's insured acres")

    # late_planted = planting_date strictly after program.final_planting_date (PRD §3.5)
    late_planted = False
    if planting_date is not None:
        final_pd = parse_iso(program["final_planting_date"], "final_planting_date")
        late_planted = planting_date > final_pd

    # Supersede any prior ACCEPTED report on the unit (PRD §3.5)
    for r in ledger.reports_of_unit(unit_id):
        if r["status"] == "ACCEPTED":
            r["status"] = "SUPERSEDED"
            touch(r)

    entity = make_common()
    entity.update({
        "unit_id": unit_id,
        "planted_acres": planted_acres,
        "prevented_acres": prevented_acres,
        "planting_date": body.get("planting_date"),
        "late_planted": late_planted,
        "status": "ACCEPTED",
    })
    db.acreage_reports[entity["id"]] = entity

    # Unit: set acreage, PENDING -> REPORTED (PRD §3.5)
    unit["planted_acres"] = planted_acres
    unit["prevented_acres"] = prevented_acres
    if unit["status"] == "PENDING":
        unit["status"] = "REPORTED"
    touch(unit)

    # Bubble up: election ELECTED -> REPORTED if all units REPORTED
    transitions.bubble_election_to_reported(election)

    # Recompute owning policy total_insured_acres
    policy = ledger.policy_of_election(election)
    if policy is not None:
        ledger.recompute_policy_insured_acres(policy, bump=True)

    return response.success_object(public(entity), 201)


@bp.get("/acreage-reports/<rid>")
def get_report(rid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    entity = lookup(db.acreage_reports, rid)
    return response.success_object(public(entity), 200)


@bp.get("/acreage-reports")
def list_reports():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    items = list(db.acreage_reports.values())
    if "unit_id" in request.args:
        items = [r for r in items if r["unit_id"] == request.args.get("unit_id")]
    page, total = paginate(items, limit, offset)
    return response.success_array(page, limit, offset, total, 200)
