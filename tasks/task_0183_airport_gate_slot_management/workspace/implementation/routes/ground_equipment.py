"""GroundEquipment registry routes + reverse-FK allocation listing."""
from flask import Blueprint, request

import db
import errors
import helpers
from middleware import authenticate, require_roles
from response import success, list_success

bp = Blueprint("ground_equipment", __name__)

EQUIPMENT_TYPES = {"GPU", "PUSHBACK_TUG", "BELT_LOADER", "AIR_START"}


@bp.route("/ground-equipment", methods=["POST"])
def create_ground_equipment():
    _, role = authenticate()
    require_roles(role, {"OpsAdmin"})
    body = helpers.get_body()
    helpers.require_fields(body, ["asset_tag", "equipment_type"])
    asset_tag = body["asset_tag"]
    if not isinstance(asset_tag, str):
        raise errors.invalid_request("asset_tag must be a string.")
    equipment_type = body["equipment_type"]
    helpers.check_enum(equipment_type, EQUIPMENT_TYPES, "equipment_type")

    turnaround = 0
    if body.get("turnaround_minutes") is not None:
        turnaround = helpers.parse_int(body["turnaround_minutes"], "turnaround_minutes", minimum=0)

    rec = {
        "id": db.new_id(),
        "asset_tag": asset_tag,
        "equipment_type": equipment_type,
        "turnaround_minutes": turnaround,
        "status": "AVAILABLE",
    }
    db.stamp_create(rec)
    db.ground_equipment[rec["id"]] = rec
    return success(helpers.serialize(rec), status=201)


@bp.route("/ground-equipment/<eid>", methods=["GET"])
def get_ground_equipment(eid):
    _, role = authenticate()
    require_roles(role, {"OpsAdmin", "RampAgent", "GateController"})
    rec = db.ground_equipment.get(eid)
    if rec is None:
        raise errors.not_found("GSE asset not found.")
    return success(helpers.serialize(rec), status=200)


@bp.route("/ground-equipment/<eid>/gse-allocations", methods=["GET"])
def allocations_for_equipment(eid):
    _, role = authenticate()
    require_roles(role, {"OpsAdmin", "RampAgent"})
    if eid not in db.ground_equipment:
        raise errors.not_found("GSE asset not found.")
    status = request.args.get("status")
    recs = [a for a in db.gse_allocations.values() if a.get("equipment_id") == eid]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, limit, offset, total = helpers.paginate(recs)
    return list_success(helpers.serialize_list(page), limit, offset, total)
