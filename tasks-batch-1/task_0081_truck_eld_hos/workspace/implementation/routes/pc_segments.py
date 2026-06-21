"""PersonalConveyanceSegment read endpoints (PRD §3.7)."""
from flask import Blueprint, request

import db
import errors
import response
import serializers as ser
import validation as val
from middleware import get_auth, require_role
from paginate import paginate

bp = Blueprint("pc_segments", __name__)


@bp.route("/eld/pc-segments/<id>", methods=["GET"])
def get_segment(id):
    _, role = get_auth()
    require_role(role, {"Driver", "CarrierAdmin", "SafetyOfficer"})
    rec = db.pc_segments.get(id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "PC segment not found.")
    return response.object_response(ser.pc_segment_view(rec), 200)


@bp.route("/eld/pc-segments", methods=["GET"])
def list_segments():
    _, role = get_auth()
    require_role(role, {"Driver", "CarrierAdmin", "SafetyOfficer"})
    limit, offset = val.get_pagination()
    items = list(db.pc_segments.values())
    driver_id = request.args.get("driver_id")
    event_id = request.args.get("event_id")
    if driver_id is not None:
        items = [r for r in items if r["driver_id"] == driver_id]
    if event_id is not None:
        items = [r for r in items if r["event_id"] == event_id]
    page, total = paginate(items, limit, offset)
    return response.array_response([ser.pc_segment_view(r) for r in page], limit, offset, total)
