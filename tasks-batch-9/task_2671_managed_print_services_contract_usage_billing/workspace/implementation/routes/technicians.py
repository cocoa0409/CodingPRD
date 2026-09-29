"""Technician registry endpoints (PRD 3.6)."""
from flask import Blueprint

import serialize
import validation as v
from auth import require
from envelope import created, ok, ok_list
from resolve import get_technician
from store import db, new_row

bp = Blueprint("technicians", __name__)

SKILL_LEVELS = ("L1", "L2", "L3")


@bp.post("/technicians")
def create_technician():
    require("AccountManager")
    body = v.body()
    full_name = v.string_field(body, "full_name")
    home_region = v.string_field(body, "home_region", upper_case=True)
    skill_level = v.enum_field(body, "skill_level", SKILL_LEVELS)
    buffer_minutes = v.int_field(body, "travel_buffer_minutes", required=False,
                                 minimum=0, maximum=120, default=30)
    row = new_row()
    row.update({
        "full_name": full_name,
        "home_region": home_region,
        "skill_level": skill_level,
        "travel_buffer_minutes": buffer_minutes,
    })
    db.technicians[row["id"]] = row
    return created(serialize.technician(row))


@bp.get("/technicians/<technician_id>")
def read_technician(technician_id):
    require("AccountManager", "FleetOpsController", "FieldTechnician")
    technician = get_technician(technician_id)
    return ok(serialize.technician(technician))


@bp.get("/technicians")
def list_technicians():
    require("AccountManager", "FleetOpsController", "FieldTechnician")
    rows = db.sorted_rows("technicians")
    for field in ("home_region", "skill_level"):
        value = v.query_filter(field)
        if value is not None:
            rows = [t for t in rows if t[field] == value]
    data, meta = v.paginate(rows, serialize.technician)
    return ok_list(data, meta)
