"""Replenishment order endpoints and state transitions."""
from flask import Blueprint, request

import errors
from db import store, now_iso
from middleware import require_auth, require_role
from response import success_object, success_list
from services import serialize, domain
from services.validate import (get_json_body, reject_unknown_fields, require_fields,
                               as_number, as_iso8601, check_range, parse_pagination)

bp = Blueprint("orders", __name__)


@bp.route("/replenishment-orders/<order_id>", methods=["GET"])
def get_order(order_id):
    require_auth()
    o = store.replenishment_orders.get(order_id)
    if o is None:
        raise errors.not_found(errors.ERR_ORDER_NOT_FOUND, "Order not found")
    return success_object(serialize.serialize_order(o))


@bp.route("/replenishment-orders", methods=["GET"])
def list_orders():
    require_auth()
    limit, offset = parse_pagination()
    vessel_id = request.args.get("vessel_id")
    trigger_reading_id = request.args.get("trigger_reading_id")
    status = request.args.get("status")
    orders = list(store.replenishment_orders.values())
    if vessel_id is not None:
        orders = [o for o in orders if o["vessel_id"] == vessel_id]
    if trigger_reading_id is not None:
        orders = [o for o in orders if o.get("trigger_reading_id") == trigger_reading_id]
    if status is not None:
        orders = [o for o in orders if o["status"] == status]
    orders.sort(key=lambda o: o["created_at"])
    total = len(orders)
    page = orders[offset:offset + limit]
    return success_list([serialize.serialize_order(o) for o in page],
                        limit=limit, offset=offset, total_count=total)


def _get_order_or_404(order_id):
    o = store.replenishment_orders.get(order_id)
    if o is None:
        raise errors.not_found(errors.ERR_ORDER_NOT_FOUND, "Order not found")
    return o


def _bump_vessel(vessel):
    vessel["updated_at"] = now_iso()
    vessel["version"] = vessel["version"] + 1


@bp.route("/replenishment-orders/<order_id>/dispatch", methods=["POST"])
def dispatch_order(order_id):
    ctx = require_auth()
    # Body (if any) must be empty/valid — endpoint takes no input fields.
    body = get_json_body()
    reject_unknown_fields(body, set())
    require_role(ctx, {"ServiceManager"})
    o = _get_order_or_404(order_id)
    if o["status"] != "TRIGGERED":
        raise errors.conflict(errors.ERR_INVALID_ORDER_STATE,
                              "Order must be TRIGGERED to dispatch")
    o["status"] = "DISPATCHED"
    o["updated_at"] = now_iso()
    o["version"] = o["version"] + 1
    return success_object(serialize.serialize_order(o))


@bp.route("/replenishment-orders/<order_id>/receive", methods=["POST"])
def receive_order(order_id):
    ctx = require_auth()
    body = get_json_body()
    reject_unknown_fields(body, {"delivered_tons", "received_at"})
    require_fields(body, ["delivered_tons", "received_at"])
    delivered = as_number(body["delivered_tons"], "delivered_tons")
    check_range(delivered, "delivered_tons", 0, None, min_exclusive=True)
    received_at = as_iso8601(body["received_at"], "received_at")

    require_role(ctx, {"PlantOperator", "Technician"})
    o = _get_order_or_404(order_id)

    v = store.vessels.get(o["vessel_id"])
    # PlantOperator may only receive for its own site.
    if ctx.role == "PlantOperator" and v is not None and ctx.user_id != v["site_id"]:
        raise errors.forbidden("PlantOperator may only receive for its own site")

    if o["status"] != "DISPATCHED":
        raise errors.conflict(errors.ERR_INVALID_ORDER_STATE,
                              "Order must be DISPATCHED to receive")

    if v is not None and v.get("scale_status") == "OUT_OF_TOLERANCE":
        raise errors.conflict(errors.ERR_SCALE_OUT_OF_TOLERANCE,
                              "Vessel scale is OUT_OF_TOLERANCE")

    o["status"] = "RECEIVED"
    o["delivered_tons"] = delivered
    o["received_at"] = received_at
    o["updated_at"] = now_iso()
    o["version"] = o["version"] + 1
    if v is not None:
        _bump_vessel(v)
    return success_object(serialize.serialize_order(o))


@bp.route("/replenishment-orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    ctx = require_auth()
    body = get_json_body()
    reject_unknown_fields(body, set())
    require_role(ctx, {"PlantOperator", "ServiceManager"})
    o = _get_order_or_404(order_id)

    v = store.vessels.get(o["vessel_id"])
    if ctx.role == "PlantOperator" and v is not None and ctx.user_id != v["site_id"]:
        raise errors.forbidden("PlantOperator may only cancel for its own site")

    if o["status"] != "TRIGGERED":
        raise errors.conflict(errors.ERR_INVALID_ORDER_STATE,
                              "Order must be TRIGGERED to cancel")

    o["status"] = "CANCELLED"
    o["updated_at"] = now_iso()
    o["version"] = o["version"] + 1
    if v is not None:
        _bump_vessel(v)
    return success_object(serialize.serialize_order(o))


@bp.route("/replenishment-orders/<order_id>/void", methods=["POST"])
def void_order(order_id):
    ctx = require_auth()
    body = get_json_body()
    reject_unknown_fields(body, set())
    require_role(ctx, {"ServiceManager"})
    o = _get_order_or_404(order_id)

    if o["status"] != "RECEIVED":
        raise errors.conflict(errors.ERR_INVALID_ORDER_STATE,
                              "Order must be RECEIVED to void")

    v = store.vessels.get(o["vessel_id"])
    if v is not None:
        # PRD 3.5: reject only when the void would drive current_inventory_tons
        # below zero. current_inventory_tons is defined by 3.2's recompute rule
        # (anchor + post-anchor RECEIVED receipts), so evaluate the recompute
        # with this order excluded from the received set. A receipt at/before
        # the anchor contributes nothing, so removing it cannot go negative.
        remaining = domain.compute_current_inventory_tons_excluding(v, o["id"])
        if remaining < 0:
            raise errors.conflict(errors.ERR_INVENTORY_WOULD_GO_NEGATIVE,
                                  "Voiding would drive inventory below zero")

    o["status"] = "VOIDED"
    o["updated_at"] = now_iso()
    o["version"] = o["version"] + 1
    if v is not None:
        _bump_vessel(v)
    return success_object(serialize.serialize_order(o))
