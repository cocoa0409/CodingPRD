"""Hospital units, posture and the computed readiness read (PRD 3.3)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import cascade
import serialize
from auth import ALL_ROLES, require_roles
from envelope import object_response
from errors import ApiError
from helpers import body, get_unit, req_enum, req_int, req_str
from store import base_entity, db

bp = Blueprint("units", __name__)

MODES = ("ATTESTED", "PROJECTED")


@bp.post("/accreditation/units")
def create_unit():
    require_roles("AccreditationDirector")
    b = body()
    name = req_str(b, "name")
    unit_type = req_enum(b, "unit_type", calc.UNIT_TYPES)
    bed_count = req_int(b, "bed_count", minimum=0)

    for existing in db.units.values():
        if existing["name"] == name:
            raise ApiError("ERR_DUPLICATE_RESOURCE", message="Unit name already registered.")

    unit = base_entity("HospitalUnit")
    unit.update(
        {
            "name": name,
            "unit_type": unit_type,
            "bed_count": bed_count,
            "posture": "OPEN",
            "open_deficiency_penalty_points": 0,
            "readiness_score": Decimal("0.00"),
            "readiness_band": "NOT_ASSESSED",
            "scheduled_tracer_count": 0,
        }
    )
    db.units[unit["id"]] = unit
    return object_response(serialize.unit(unit), 201)


@bp.get("/accreditation/units/<unit_id>")
def read_unit(unit_id):
    require_roles(*ALL_ROLES)
    unit = get_unit(unit_id)
    return object_response(serialize.unit(unit))


@bp.get("/accreditation/units/<unit_id>/readiness")
def read_readiness(unit_id):
    require_roles(*ALL_ROLES)
    raw_mode = request.args.get("mode")
    if raw_mode is None or raw_mode == "":
        mode = "ATTESTED"
    elif raw_mode in MODES:
        mode = raw_mode
    else:
        raise ApiError("ERR_INVALID_REQUEST", message="'mode' must be ATTESTED or PROJECTED.")

    unit = get_unit(unit_id)
    result = cascade.compute_readiness(unit, mode)
    return object_response(serialize.readiness(result))
