"""Accessory kit stock reads (PRD §3.5); creation lives on the center route."""
from flask import Blueprint

import db
import validation as v
from middleware import OPS_ROLES, authenticate
from response import list_response, object_response
from services import serializers as ser
from services import state

bp = Blueprint("kits", __name__)


@bp.route("/vpc/accessory-kits/<kit_id>", methods=["GET"])
def read_kit(kit_id):
    authenticate(OPS_ROLES)
    kit = db.must_get("kits", kit_id)
    state.recompute_kit(kit)
    return object_response(ser.kit(kit))


@bp.route("/vpc/accessory-kits", methods=["GET"])
def list_kits():
    authenticate(OPS_ROLES)
    center_id = v.query_filter("processing_center_id")
    program_code = v.query_filter("program_code")
    kit_code = v.query_filter("kit_code")
    records = db.ordered(db.kits)
    for kit in records:
        state.recompute_kit(kit)
    if center_id is not None:
        records = [r for r in records if r["processing_center_id"] == center_id]
    if program_code is not None:
        records = [r for r in records if r["program_code"] == program_code]
    if kit_code is not None:
        records = [r for r in records if r["kit_code"] == kit_code]
    items, limit, offset, total = v.paginate(records, ser.kit)
    return list_response(items, limit, offset, total)
