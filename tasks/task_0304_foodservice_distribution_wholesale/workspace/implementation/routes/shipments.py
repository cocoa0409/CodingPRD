"""Shipment routes: reads, load, proof-of-delivery."""
from flask import Blueprint

import db
import errors
import middleware
import models
import response
from routes.listing import list_response
from services import lookup, serialize

bp = Blueprint("shipments", __name__)

READ_ROLES = {"DistributorAdmin", "SalesRep", "WarehouseOp", "CreditManager"}


@bp.route("/shipments/<shipment_id>", methods=["GET"])
def get_shipment(shipment_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    rec = lookup.shipment(shipment_id)
    return response.object_response(serialize.shipment(rec), 200)


@bp.route("/shipments", methods=["GET"])
def list_shipments():
    _, role = middleware.require_auth()
    middleware.require_role(role, READ_ROLES)
    return list_response(db.shipments.values(), serialize.shipment,
                         {"order_id": "order_id",
                          "distributor_id": "distributor_id",
                          "warehouse_id": "warehouse_id"})


@bp.route("/shipments/<shipment_id>/load", methods=["POST"])
def load_shipment(shipment_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, {"WarehouseOp"})
    with db.lock:
        shipment = lookup.shipment(shipment_id)
        order = db.orders[shipment["order_id"]]
        # Requires shipment PICKING and parent order fulfillment_status PICKING.
        if shipment["status"] != "PICKING":
            raise errors.invalid_state("Shipment is not in PICKING.")
        if order["fulfillment_status"] != "PICKING":
            raise errors.invalid_state("Parent order is not in PICKING.")
        shipment["status"] = "LOADED"
        models.touch(shipment)
        order["fulfillment_status"] = "LOADED"
        models.touch(order)
        return response.object_response(serialize.shipment(shipment), 200)


@bp.route("/shipments/<shipment_id>/pod", methods=["POST"])
def pod_shipment(shipment_id):
    _, role = middleware.require_auth()
    middleware.require_role(role, {"WarehouseOp"})
    body = middleware.get_json_body()
    pod_signature = body.get("pod_signature")
    with db.lock:
        shipment = lookup.shipment(shipment_id)
        order = db.orders[shipment["order_id"]]
        # State: requires shipment LOADED.
        if shipment["status"] != "LOADED":
            raise errors.invalid_state("Shipment is not in LOADED.")
        # Business: non-empty pod_signature required.
        if not pod_signature or not isinstance(pod_signature, str) or pod_signature.strip() == "":
            raise errors.ApiError(errors.ERR_POD_SIGNATURE_REQUIRED, 422,
                                  "A non-empty pod_signature is required.")
        shipment["pod_signature"] = pod_signature
        shipment["status"] = "DELIVERED"
        order["fulfillment_status"] = "DELIVERED"
        order["settled"] = True

        # Inventory consumption: for each allocated lot, decrement on_hand_splits
        # and reserved_splits by what the line reserved (PRD §3.6).
        lines = lookup.lines_of_order(order["id"])
        for line in lines:
            alloc = line.get("_lot_allocations") or {}
            for lot_id, splits in alloc.items():
                lot = db.inventory_lots.get(lot_id)
                if lot is None or splits <= 0:
                    continue
                lot["on_hand_splits"] -= splits
                lot["reserved_splits"] -= splits
                models.touch(lot)

        shipment["delivered_total_cents"] = order["order_total_cents"]
        models.touch(shipment)
        models.touch(order)
        return response.object_response(serialize.shipment(shipment), 200)
