"""Shop resource endpoints: HardwareTemplate, MoulderMachine, SprayBooth (PRD §3.1)."""

from flask import Blueprint, request

import db
from errors import err
from middleware import (get_context, require_role, json_body, req_string, req_bool,
                        req_int, req_enum, require_existence)
from response import success, list_response, parse_pagination

bp = Blueprint("resources", __name__)

SPECIES = ("OAK", "MAPLE", "CHERRY", "WALNUT", "PAINT_GRADE")


# ---------------------------------------------------------------- HardwareTemplate

def serialize_template(t):
    return {
        "id": t["id"],
        "template_code": t["template_code"],
        "manufacturer": t["manufacturer"],
        "fire_rated_compatible": t["fire_rated_compatible"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


@bp.post("/hardware-templates")
def create_template():
    _, role = get_context()
    require_role(role, "PlantManager")
    body = json_body(required=("template_code", "manufacturer", "fire_rated_compatible"))
    template_code = req_string(body, "template_code")
    manufacturer = req_string(body, "manufacturer")
    fire_rated_compatible = req_bool(body, "fire_rated_compatible")
    rec = db.new_record()
    rec.update({
        "template_code": template_code,
        "manufacturer": manufacturer,
        "fire_rated_compatible": fire_rated_compatible,
    })
    db.hardware_templates[rec["id"]] = rec
    return success(serialize_template(rec), status=201)


@bp.get("/hardware-templates")
def list_templates():
    get_context()
    limit, offset = parse_pagination(request.args)
    code = request.args.get("template_code")
    items = [t for t in db.hardware_templates.values() if code is None or t["template_code"] == code]
    return list_response(items, limit, offset, serialize_template)


@bp.get("/hardware-templates/<tid>")
def get_template(tid):
    get_context()
    template = require_existence(db.hardware_templates, tid, "ERR_TEMPLATE_NOT_FOUND", "HardwareTemplate")
    return success(serialize_template(template))


# ---------------------------------------------------------------- MoulderMachine

def serialize_machine(m):
    return {
        "id": m["id"],
        "machine_code": m["machine_code"],
        "supported_species": list(m["supported_species"]),
        "active": m["active"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


@bp.post("/moulder-machines")
def create_machine():
    _, role = get_context()
    require_role(role, "PlantManager")
    body = json_body(required=("machine_code", "supported_species"), optional=("active",))
    machine_code = req_string(body, "machine_code")
    supported = body.get("supported_species")
    if not isinstance(supported, list) or any(not isinstance(s, str) or s not in SPECIES for s in supported):
        raise err("ERR_INVALID_REQUEST",
                  "supported_species must be a list subset of OAK|MAPLE|CHERRY|WALNUT|PAINT_GRADE")
    active = body.get("active", True)
    if not isinstance(active, bool):
        raise err("ERR_INVALID_REQUEST", "active must be a boolean")
    rec = db.new_record()
    rec.update({
        "machine_code": machine_code,
        "supported_species": list(supported),
        "active": active,
    })
    db.moulder_machines[rec["id"]] = rec
    return success(serialize_machine(rec), status=201)


@bp.get("/moulder-machines")
def list_machines():
    get_context()
    limit, offset = parse_pagination(request.args)
    code = request.args.get("machine_code")
    items = [m for m in db.moulder_machines.values() if code is None or m["machine_code"] == code]
    return list_response(items, limit, offset, serialize_machine)


@bp.get("/moulder-machines/<mid>")
def get_machine(mid):
    get_context()
    machine = require_existence(db.moulder_machines, mid, "ERR_MACHINE_NOT_FOUND", "MoulderMachine")
    return success(serialize_machine(machine))


# ---------------------------------------------------------------- SprayBooth

def serialize_booth(b):
    return {
        "id": b["id"],
        "booth_code": b["booth_code"],
        "capacity": b["capacity"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


@bp.post("/spray-booths")
def create_booth():
    _, role = get_context()
    require_role(role, "PlantManager")
    body = json_body(required=("booth_code",), optional=("capacity",))
    booth_code = req_string(body, "booth_code")
    capacity = body.get("capacity", 2)
    if isinstance(capacity, bool) or not isinstance(capacity, int):
        raise err("ERR_INVALID_REQUEST", "capacity must be an integer")
    rec = db.new_record()
    rec.update({"booth_code": booth_code, "capacity": capacity})
    db.spray_booths[rec["id"]] = rec
    return success(serialize_booth(rec), status=201)


@bp.get("/spray-booths")
def list_booths():
    get_context()
    limit, offset = parse_pagination(request.args)
    code = request.args.get("booth_code")
    items = [b for b in db.spray_booths.values() if code is None or b["booth_code"] == code]
    return list_response(items, limit, offset, serialize_booth)


@bp.get("/spray-booths/<bid>")
def get_booth(bid):
    get_context()
    booth = require_existence(db.spray_booths, bid, "ERR_BOOTH_NOT_FOUND", "SprayBooth")
    return success(serialize_booth(booth))
