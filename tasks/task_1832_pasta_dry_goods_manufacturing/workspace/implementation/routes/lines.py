"""ProductionLine endpoints and the gluten posture cycle."""
from flask import Blueprint

import db
from db import new_common, new_id, store, touch
from errors import ApiError
from middleware import ALL_ROLES, get_context, require_roles
from response import created, ok
from services.calc import line_has_inflight_run
from validation import parse_body, require_path_entity

bp = Blueprint("lines", __name__)


@bp.post("/production-lines")
def create_line():
    get_context()
    require_roles(["PlantManager"])
    body = parse_body({"line_name": ("string", True, None)}, allow_empty=False)
    line = {
        "id": new_id(),
        "line_name": body["line_name"],
        "gluten_posture": "GLUTEN_EXPOSED",
        "cleaning_completed_at": None,
    }
    new_common(line)
    store.production_lines[line["id"]] = line
    return created(line)


@bp.get("/production-lines/<line_id>")
def get_line(line_id):
    get_context()
    require_roles(ALL_ROLES)
    return ok(require_path_entity(store.production_lines, line_id, "ERR_LINE_NOT_FOUND"))


@bp.post("/production-lines/<line_id>/start-cleaning")
def start_cleaning(line_id):
    get_context()
    require_roles(["ProductionOperator"])
    line = require_path_entity(store.production_lines, line_id, "ERR_LINE_NOT_FOUND")
    if line["gluten_posture"] not in ("GLUTEN_EXPOSED", "GF_VALIDATED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "start-cleaning requires posture GLUTEN_EXPOSED or GF_VALIDATED")
    if line_has_inflight_run(line["id"]):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Cannot start cleaning while a run is in flight on this line")
    line["gluten_posture"] = "CLEANING_IN_PROGRESS"
    touch(line)
    return ok(line)


@bp.post("/production-lines/<line_id>/complete-cleaning")
def complete_cleaning(line_id):
    get_context()
    require_roles(["ProductionOperator"])
    line = require_path_entity(store.production_lines, line_id, "ERR_LINE_NOT_FOUND")
    if line["gluten_posture"] != "CLEANING_IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "complete-cleaning requires posture CLEANING_IN_PROGRESS")
    line["gluten_posture"] = "AWAITING_SWAB"
    line["cleaning_completed_at"] = db.clock_now()
    touch(line)
    return ok(line)
