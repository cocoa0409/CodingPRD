"""Crew endpoints (PRD 3.3)."""
from flask import Blueprint

from db import new_record, store
from domain import require_active, ser_crew
from errors import raise_error
from middleware import ALL_ROLES, get_caller, locked, require_roles
from response import success_object
from validate import get_body, req_int, req_str
from routes.common import list_endpoint, require_record

bp = Blueprint("crews", __name__)

PM = ["ProgramManager"]


@bp.route("/streetlights/crews", methods=["POST"])
@locked
def create_crew():
    caller = get_caller()
    body = get_body()
    program_id = req_str(body, "program_id")
    crew_name = req_str(body, "crew_name")
    base_stops = req_int(body, "base_stops_per_shift", positive=True)
    rate = req_int(body, "hourly_rate_cents", positive=True)
    require_roles(caller, PM)
    program = store.programs.get(program_id)
    if program is None:
        raise_error("ERR_PROGRAM_NOT_FOUND", f"program not found: {program_id}")
    require_active(program)
    rec = new_record("crews", {
        "program_id": program_id,
        "crew_name": crew_name,
        "base_stops_per_shift": base_stops,
        "hourly_rate_cents": rate,
    })
    return success_object(ser_crew(rec), status=201)


@bp.route("/streetlights/crews", methods=["GET"])
@locked
def list_crews():
    return list_endpoint("crews", ser_crew, ["program_id"])


@bp.route("/streetlights/crews/<cid>", methods=["GET"])
@locked
def get_crew(cid):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    rec = require_record("crews", cid, "ERR_CREW_NOT_FOUND")
    return success_object(ser_crew(rec))
