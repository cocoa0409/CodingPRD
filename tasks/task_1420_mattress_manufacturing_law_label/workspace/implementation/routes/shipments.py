"""Shipment endpoints."""
from flask import Blueprint, request

import clock
import db
import errors
import middleware
import response
from routes.helpers import as_string, body, require
from services import calc, cascade

bp = Blueprint("shipments", __name__)


def shipment_view(s):
    return {
        "id": s["id"],
        "order_id": s["order_id"],
        "retailer_id": s["retailer_id"],
        "destination_state_code": s["destination_state_code"],
        "unit_ids": s["unit_ids"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def get_shipment(shipment_id):
    s = db.shipments.get(shipment_id)
    if s is None:
        errors.raise_err(errors.ERR_SHIPMENT_NOT_FOUND, "shipment not found")
    return s


@bp.route("/shipments", methods=["POST"])
def create_shipment():
    middleware.require_roles(["LogisticsCoordinator"])
    data = body()
    order_id = as_string(require(data, "order_id"), "order_id")
    order = db.orders.get(order_id)
    if order is None:
        errors.raise_err(errors.ERR_ORDER_NOT_FOUND, "order not found")
    unit_ids = require(data, "unit_ids")
    if not isinstance(unit_ids, list) or len(unit_ids) == 0 or any(
        not isinstance(u, str) for u in unit_ids
    ):
        errors.raise_err(errors.ERR_VALIDATION_FAILED, "unit_ids must be a non-empty list of ids")
    # tier 5: order must be COMPLETE
    if order["production_status"] != "COMPLETE":
        errors.raise_err(errors.ERR_ORDER_NOT_COMPLETE, "order must be COMPLETE")
    # tier 6: ACTIVE law label for (model, destination_state)
    if cascade.active_label_for(order["model_id"], order["destination_state_code"]) is None:
        errors.raise_err(errors.ERR_LABEL_NOT_ACTIVE, "no ACTIVE law label for model and state")
    # tier 6: APPROVED unexpired flammability cert
    if not cascade.approved_unexpired_flammability_certs(order["model_id"]):
        errors.raise_err(
            errors.ERR_CERT_EXPIRED,
            "model flammability certificate expired or absent",
        )
    # tier 5/10: unit states and order membership
    units = []
    for uid in unit_ids:
        unit = db.units.get(uid)
        if unit is None:
            errors.raise_err(errors.ERR_UNIT_NOT_FOUND, "unit not found")
        units.append(unit)
    for unit in units:
        if unit["status"] != "MANUFACTURED":
            errors.raise_err(errors.ERR_UNITS_NOT_MANUFACTURED, "all units must be MANUFACTURED")
    for unit in units:
        if unit["order_id"] != order["id"]:
            errors.raise_err(errors.ERR_UNIT_ORDER_MISMATCH, "unit does not belong to the order")
    shipment = {
        "id": db.new_id(),
        "order_id": order["id"],
        "retailer_id": order["retailer_id"],
        "destination_state_code": order["destination_state_code"],
        "unit_ids": list(unit_ids),
        "status": "CREATED",
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
    }
    db.put(db.shipments, shipment)
    return response.success_object(shipment_view(shipment), 201)


@bp.route("/shipments", methods=["GET"])
def list_shipments():
    middleware.require_roles(middleware.ALL_ROLES)
    items = list(db.shipments.values())
    for param in ("order_id", "retailer_id", "status"):
        q = request.args.get(param)
        if q is not None:
            items = [s for s in items if s[param] == q]
    items.sort(key=lambda s: s["_seq"])
    return response.success_list([shipment_view(s) for s in items])


@bp.route("/shipments/<shipmentId>", methods=["GET"])
def get_one_shipment(shipmentId):
    middleware.require_roles(middleware.ALL_ROLES)
    s = get_shipment(shipmentId)
    return response.success_object(shipment_view(s))


@bp.route("/shipments/<shipmentId>/dispatch", methods=["POST"])
def dispatch_shipment(shipmentId):
    middleware.require_roles(["LogisticsCoordinator"])
    shipment = get_shipment(shipmentId)
    if shipment["status"] != "CREATED":
        errors.raise_err(errors.ERR_SHIPMENT_NOT_CREATED, "shipment must be CREATED")
    for uid in shipment["unit_ids"]:
        unit = db.units[uid]
        unit["status"] = "SHIPPED"
        cascade.bump(unit)
    shipment["status"] = "DISPATCHED"
    cascade.bump(shipment)
    order = db.orders[shipment["order_id"]]
    if calc.fulfillment_recompute(order):
        cascade.bump(order)
    return response.success_object(shipment_view(shipment))


@bp.route("/shipments/<shipmentId>/deliver", methods=["POST"])
def deliver_shipment(shipmentId):
    middleware.require_roles(["LogisticsCoordinator"])
    shipment = get_shipment(shipmentId)
    if shipment["status"] != "DISPATCHED":
        errors.raise_err(errors.ERR_SHIPMENT_NOT_DISPATCHED, "shipment must be DISPATCHED")
    now_iso = clock.now_iso()
    for uid in shipment["unit_ids"]:
        unit = db.units[uid]
        unit["status"] = "DELIVERED"
        unit["delivered_at"] = now_iso
        cascade.bump(unit)
    shipment["status"] = "DELIVERED"
    cascade.bump(shipment)
    order = db.orders[shipment["order_id"]]
    if calc.fulfillment_recompute(order):
        cascade.bump(order)
    return response.success_object(shipment_view(shipment))
