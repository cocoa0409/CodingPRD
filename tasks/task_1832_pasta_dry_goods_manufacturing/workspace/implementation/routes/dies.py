"""ExtrusionDie endpoints: registry, mount/unmount, cleaning and auto-retire."""
from flask import Blueprint

import db
from db import new_common, new_id, store, touch
from errors import ApiError
from middleware import ALL_ROLES, get_context, require_roles
from response import created, ok, paginate
from services.calc import line_has_inflight_run
from validation import fk_exists, parse_body, raw_body, require_path_entity, validate_schema

bp = Blueprint("dies", __name__)

SHAPE_FAMILIES = ["LONG_CUT", "SHORT_CUT", "SPECIALTY"]


@bp.post("/extrusion-dies")
def create_die():
    get_context()
    require_roles(["PlantManager"])
    body = parse_body({
        "die_code": ("string", True, None),
        "shape_family": ("enum", True, SHAPE_FAMILIES),
        "rated_capacity_kg": ("number", True, None),
    }, allow_empty=False)
    if db.dec(body["rated_capacity_kg"]) <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "rated_capacity_kg must be > 0")
    die = {
        "id": new_id(),
        "die_code": body["die_code"],
        "shape_family": body["shape_family"],
        "rated_capacity_kg": body["rated_capacity_kg"],
        "extruded_kg": 0,
        "status": "AVAILABLE",
        "mounted_line_id": None,
    }
    new_common(die)
    store.extrusion_dies[die["id"]] = die
    return created(die)


@bp.get("/extrusion-dies")
def list_dies():
    get_context()
    require_roles(ALL_ROLES)
    rows = list(store.extrusion_dies.values())
    rows = paginate.filter(rows, "mounted_line_id")
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/extrusion-dies/<die_id>")
def get_die(die_id):
    get_context()
    require_roles(ALL_ROLES)
    return ok(require_path_entity(store.extrusion_dies, die_id, "ERR_DIE_NOT_FOUND"))


@bp.post("/extrusion-dies/<die_id>/mount")
def mount_die(die_id):
    get_context()
    require_roles(["ProductionOperator"])
    die = require_path_entity(store.extrusion_dies, die_id, "ERR_DIE_NOT_FOUND")
    body = raw_body()
    line = fk_exists(store.production_lines, body, "line_id", "ERR_LINE_NOT_FOUND")
    validate_schema(body, {"line_id": ("string", True, None)})
    if die["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an AVAILABLE die can be mounted")
    for other in store.extrusion_dies.values():
        if (other["id"] != die["id"] and other["status"] == "MOUNTED"
                and other["mounted_line_id"] == line["id"]):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Another die is already MOUNTED on the target line")
    if line_has_inflight_run(line["id"]):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Cannot mount while a run is in flight on the target line")
    die["status"] = "MOUNTED"
    die["mounted_line_id"] = line["id"]
    touch(die)
    return ok(die)


@bp.post("/extrusion-dies/<die_id>/unmount")
def unmount_die(die_id):
    get_context()
    require_roles(["ProductionOperator"])
    die = require_path_entity(store.extrusion_dies, die_id, "ERR_DIE_NOT_FOUND")
    if die["status"] != "MOUNTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a MOUNTED die can be unmounted")
    if line_has_inflight_run(die["mounted_line_id"]):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Cannot unmount while a run is in flight on the die's line")
    die["status"] = "IN_CLEANING"
    die["mounted_line_id"] = None
    touch(die)
    return ok(die)


@bp.post("/extrusion-dies/<die_id>/complete-cleaning")
def complete_die_cleaning(die_id):
    get_context()
    require_roles(["ProductionOperator"])
    die = require_path_entity(store.extrusion_dies, die_id, "ERR_DIE_NOT_FOUND")
    body = parse_body({"refurbish": ("boolean", False, None)})
    if die["status"] != "IN_CLEANING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "complete-cleaning requires status IN_CLEANING")
    refurbish = body.get("refurbish", False)
    if refurbish:
        die["extruded_kg"] = 0
        die["status"] = "AVAILABLE"
    elif db.dec(die["extruded_kg"]) >= db.dec(die["rated_capacity_kg"]):
        die["status"] = "RETIRED"  # wear limit forces automatic retirement
    else:
        die["status"] = "AVAILABLE"
    touch(die)
    return ok(die)
