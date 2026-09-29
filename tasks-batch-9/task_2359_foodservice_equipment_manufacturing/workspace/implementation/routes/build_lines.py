"""BuildLine endpoints (PRD Section 3.7)."""
from flask import Blueprint

import validate
from db import db, insert, ordered
from middleware import authorize
from response import ok, created, ok_list
from routes.helpers import find, filter_by, unique_code
from services import calc

bp = Blueprint("build_lines", __name__)


@bp.post("/build-lines")
def create_build_line():
    authorize("ProductionPlanner", "PlatformAdmin")
    payload = validate.body()
    line_code = validate.string_field(payload, "line_code", min_len=1, max_len=32)
    plant_code = validate.string_field(payload, "plant_code", min_len=1, max_len=32)
    daily_capacity_units = validate.int_field(payload, "daily_capacity_units", minimum=1)
    supported_energy_types = validate.enum_array_field(payload, "supported_energy_types",
                                                       calc.ENERGY_TYPE_MEMBERS)

    unique_code(db.build_lines, line_code=line_code)

    line = insert(db.build_lines, {
        "line_code": line_code,
        "plant_code": plant_code,
        "daily_capacity_units": daily_capacity_units,
        "supported_energy_types": supported_energy_types,
        "committed_units": 0,
    })
    return created(line)


@bp.get("/build-lines")
def list_build_lines():
    authorize("ProductionPlanner", "PlatformAdmin")
    limit, offset = validate.pagination()
    plant_code = validate.str_arg("plant_code")
    items = filter_by(ordered(db.build_lines), "plant_code", plant_code)
    return ok_list(items, limit, offset)


@bp.get("/build-lines/<line_id>")
def get_build_line(line_id):
    authorize("ProductionPlanner", "PlatformAdmin")
    line = find(db.build_lines, line_id, "ERR_PRODUCTION_RESOURCE_NOT_FOUND")
    return ok(line)
