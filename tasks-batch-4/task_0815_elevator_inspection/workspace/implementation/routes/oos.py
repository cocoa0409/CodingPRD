from flask import Blueprint, request

import errors
from auth import require
from common import (
    get_body,
    lookup,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_string,
)
from constants import OOS_REASONS
from envelope import array_response, object_response
from services import logic
from services.logic import serialize_oos
from store import db

bp = Blueprint("oos", __name__)


@bp.route("/out-of-service-orders", methods=["POST"])
@require("SafetyAdministrator")
def create_oos():
    body = get_body()
    device_id = require_string(body, "device_id")
    reason = require_enum(body, "reason", OOS_REASONS)
    start = require_int(body, "effective_start_period")
    end = require_int(body, "effective_end_period")
    citation_id = body.get("citation_id")

    device = lookup(db.devices, device_id, "ERR_DEVICE_NOT_FOUND")
    if citation_id is not None:
        if not isinstance(citation_id, str):
            raise errors.invalid_request("citation_id must be a string.")
        lookup(db.citations, citation_id, "ERR_CITATION_NOT_FOUND")

    # Overlap check (closed interval) against ACTIVE orders (priority 13).
    for o in db.oos_orders.values():
        if o["device_id"] == device_id and o["status"] == "ACTIVE":
            if start <= o["effective_end_period"] and o["effective_start_period"] <= end:
                raise errors.ApiError("ERR_OOS_ORDER_OVERLAP", 409,
                                      "Order window overlaps an active order.")

    order = logic.create_oos_order(device, reason, start, end, citation_id)
    return object_response(serialize_oos(order), 201)


@bp.route("/out-of-service-orders/<order_id>", methods=["GET"])
@require("Registrar", "SafetyAdministrator", "LicensedInspector", "BuildingOwner")
def get_oos(order_id):
    o = lookup(db.oos_orders, order_id, "ERR_OOS_ORDER_NOT_FOUND")
    return object_response(serialize_oos(o), 200)


@bp.route("/out-of-service-orders", methods=["GET"])
@require("Registrar", "SafetyAdministrator", "LicensedInspector", "BuildingOwner")
def list_oos():
    limit, offset = parse_pagination()
    device_id = request.args.get("device_id")
    citation_id = request.args.get("citation_id")
    status = request.args.get("status")
    items = list(db.oos_orders.values())
    if device_id is not None:
        items = [o for o in items if o["device_id"] == device_id]
    if citation_id is not None:
        items = [o for o in items if o.get("citation_id") == citation_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_oos(o) for o in page], limit, offset, total)


@bp.route("/out-of-service-orders/<order_id>/lift", methods=["POST"])
@require("SafetyAdministrator")
def lift_oos(order_id):
    o = lookup(db.oos_orders, order_id, "ERR_OOS_ORDER_NOT_FOUND")
    if o["status"] != "ACTIVE":
        raise errors.ApiError("ERR_OOS_ORDER_NOT_ACTIVE", 409,
                              "Order is not ACTIVE.")
    logic.lift_oos_order(o)
    return object_response(serialize_oos(o), 200)
