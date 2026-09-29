"""Hold order reads and lifting (PRD §3.7); application lives on the center route."""
from flask import Blueprint

import db
import validation as v
from errors import fail, invalid_state
from middleware import OPS_ROLES, ROLE_MANAGER, authenticate
from response import list_response, object_response
from services import serializers as ser
from services import state

bp = Blueprint("holds", __name__)


@bp.route("/vpc/hold-orders/<hold_order_id>", methods=["GET"])
def read_hold(hold_order_id):
    authenticate(OPS_ROLES)
    hold = db.must_get("hold_orders", hold_order_id)
    return object_response(ser.hold_order(hold))


@bp.route("/vpc/hold-orders", methods=["GET"])
def list_holds():
    authenticate(OPS_ROLES)
    center_id = v.query_filter("processing_center_id")
    vehicle_id = v.query_filter("vehicle_id")
    hold_type = v.query_filter("hold_type")
    scope_type = v.query_filter("scope_type")
    status = v.query_filter("status")
    model_line = v.query_filter("model_line")
    records = db.ordered(db.hold_orders)
    if center_id is not None:
        records = [r for r in records if r["processing_center_id"] == center_id]
    if vehicle_id is not None:
        records = [r for r in records if r["vehicle_id"] == vehicle_id]
    if hold_type is not None:
        records = [r for r in records if r["hold_type"] == hold_type]
    if scope_type is not None:
        records = [r for r in records if r["scope_type"] == scope_type]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if model_line is not None:
        records = [r for r in records if r["model_line"] == model_line]
    items, limit, offset, total = v.paginate(records, ser.hold_order)
    return list_response(items, limit, offset, total)


@bp.route("/vpc/hold-orders/<hold_order_id>/lift", methods=["POST"])
def lift_hold(hold_order_id):
    user_id, _role = authenticate([ROLE_MANAGER])
    hold = db.must_get("hold_orders", hold_order_id)

    if hold["status"] != "OPEN":
        invalid_state("only an OPEN hold can be lifted")
    if hold["applied_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES", "the lifter of a hold may not be the applier")

    hold["status"] = "LIFTED"
    hold["lifted_by_user_id"] = user_id
    db.touch(hold)

    for vehicle in db.ordered(db.vehicles):
        if vehicle["blocking_hold_order_id"] != hold["id"]:
            continue
        remaining = state.open_holds_covering(vehicle, exclude_hold_id=hold["id"])
        if remaining:
            vehicle["blocking_hold_order_id"] = remaining[0]["id"]
        else:
            vehicle["stop_ship_blocked"] = False
            vehicle["blocking_hold_order_id"] = None
        db.touch(vehicle)
    return object_response(ser.hold_order(hold))
