"""Program election endpoints (PRD §3.4)."""

from flask import Blueprint, request

import db
from clock import now_dt, _parse_iso
from errors import (
    ApiError, ERR_ELECTION_WINDOW_CLOSED, invalid_request, invalid_state,
    stale_farm_version,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, paginate
from services.helpers import (
    get_farm_or_404, get_election_or_404, active_membership,
    active_election_for, enrollment_references_election,
)
from validation import body, require_int, require_string, require_enum

bp = Blueprint("elections", __name__)

COMMODITIES = ("CORN", "SOYBN", "WHEAT", "COTTON")
ELECTION_CODES = ("PLC", "ARC_CO", "ARC_IC")

# Election window for the 2026 crop year (PRD §3.4).
ELECTION_DEADLINE = _parse_iso("2026-03-16T23:59:59Z")


@bp.post("/fsa/farms/<farm_id>/program-elections")
def create_election(farm_id):
    user_id, _ = require_roles(["Producer"])
    farm = get_farm_or_404(farm_id)
    data = body()
    program_year = require_int(data, "program_year")
    commodity = require_enum(data, "commodity", COMMODITIES)
    election_code = require_enum(data, "election_code", ELECTION_CODES)
    expected_farm_version = data.get("expected_farm_version")
    if expected_farm_version is None or isinstance(expected_farm_version, bool) \
            or not isinstance(expected_farm_version, int):
        raise invalid_request("expected_farm_version is required and must be an integer")

    # Producer must hold an ACTIVE membership on the farm.
    if active_membership(farm_id, user_id) is None:
        raise invalid_request("Producer does not hold an ACTIVE membership on this farm")

    # State: prior election (if any) must not be referenced by a CERTIFIED+
    # enrollment (supersession precondition).
    prior = active_election_for(farm_id, program_year, commodity)
    if prior is not None and enrollment_references_election(prior["id"]) is not None:
        raise invalid_state(
            "An enrollment referencing the prior election is CERTIFIED or beyond")

    # OCC (priority 5 — after state, before temporal/business rules).
    if expected_farm_version != farm["version"]:
        raise stale_farm_version()

    # Temporal: election window (priority 7).
    if now_dt() > ELECTION_DEADLINE:
        raise ApiError(
            ERR_ELECTION_WINDOW_CLOSED,
            "Election create/supersede/withdraw after 2026-03-16 deadline",
            422,
        )

    if prior is not None:
        prior["election_status"] = "SUPERSEDED"
        db.touch(prior)

    election = db.common_fields()
    election.update({
        "farm_id": farm_id,
        "program_year": program_year,
        "commodity": commodity,
        "election_code": election_code,
        "election_status": "ACTIVE",
        "effective_from_version": farm["version"],
    })
    db.program_elections[election["id"]] = election

    # Supersede advances Farm.version by 1 (PRD §3.4).
    farm["version"] += 1
    farm["updated_at"] = db.wall_timestamp()

    return success_object(election, 201)


@bp.get("/fsa/program-elections/<election_id>")
def get_election(election_id):
    require_roles(ALL_ROLES)
    return success_object(get_election_or_404(election_id))


@bp.get("/fsa/program-elections/<election_id>/enrollments")
def list_election_enrollments(election_id):
    require_roles(ALL_ROLES)
    get_election_or_404(election_id)
    items = [
        e for e in db.enrollments.values()
        if e.get("pinned_election_id") == election_id
    ]
    items.sort(key=lambda e: e["created_at"])
    return paginate(items, request.args)


@bp.get("/fsa/farms/<farm_id>/program-elections")
def list_farm_elections(farm_id):
    require_roles(ALL_ROLES)
    get_farm_or_404(farm_id)
    program_year = request.args.get("program_year")
    commodity = request.args.get("commodity")
    items = [e for e in db.program_elections.values() if e["farm_id"] == farm_id]
    if program_year is not None:
        try:
            py = int(program_year)
        except ValueError:
            raise invalid_request("program_year must be an integer")
        items = [e for e in items if e["program_year"] == py]
    if commodity is not None:
        items = [e for e in items if e["commodity"] == commodity]
    items.sort(key=lambda e: e["created_at"])
    return paginate(items, request.args)


@bp.post("/fsa/program-elections/<election_id>/withdraw")
def withdraw_election(election_id):
    user_id, _ = require_roles(["Producer"])
    election = get_election_or_404(election_id)
    if election["election_status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE election may be withdrawn")
    # Temporal: election window (priority 7).
    if now_dt() > ELECTION_DEADLINE:
        raise ApiError(
            ERR_ELECTION_WINDOW_CLOSED,
            "Election create/supersede/withdraw after 2026-03-16 deadline",
            422,
        )
    if enrollment_references_election(election_id) is not None:
        raise invalid_state(
            "An enrollment referencing this election is CERTIFIED or beyond")
    election["election_status"] = "WITHDRAWN"
    db.touch(election)
    return success_object(election)
