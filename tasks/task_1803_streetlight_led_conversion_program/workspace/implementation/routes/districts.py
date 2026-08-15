"""ServiceDistrict endpoints (PRD 3.1)."""
from flask import Blueprint

from db import new_record, store
from domain import CCT_CAP_KELVIN, FULL_CUTOFF_ZONES, require_active, ser_district
from errors import raise_error
from middleware import ALL_ROLES, get_caller, locked, require_roles
from response import success_object
from validate import get_body, req_enum, req_str
from routes.common import list_endpoint, require_record

bp = Blueprint("districts", __name__)

PM = ["ProgramManager"]
ZONES = ["RESIDENTIAL", "ARTERIAL", "DOWNTOWN", "RURAL"]


@bp.route("/streetlights/districts", methods=["POST"])
@locked
def create_district():
    caller = get_caller()
    body = get_body()
    program_id = req_str(body, "program_id")
    district_name = req_str(body, "district_name")
    zone = req_enum(body, "zone", ZONES)
    require_roles(caller, PM)
    program = store.programs.get(program_id)
    if program is None:
        raise_error("ERR_PROGRAM_NOT_FOUND", f"program not found: {program_id}")
    require_active(program)
    for d in store.districts.values():
        if d["program_id"] == program_id and d["district_name"] == district_name:
            raise_error("ERR_INVALID_REQUEST", "district_name must be unique within the program")
    rec = new_record("districts", {
        "program_id": program_id,
        "district_name": district_name,
        "zone": zone,
        "cct_cap_kelvin": CCT_CAP_KELVIN[zone],
        "full_cutoff_required": zone in FULL_CUTOFF_ZONES,
    })
    return success_object(ser_district(rec), status=201)


@bp.route("/streetlights/districts", methods=["GET"])
@locked
def list_districts():
    return list_endpoint("districts", ser_district, ["program_id", "zone"])


@bp.route("/streetlights/districts/<did>", methods=["GET"])
@locked
def get_district(did):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    rec = require_record("districts", did, "ERR_DISTRICT_NOT_FOUND")
    return success_object(ser_district(rec))
