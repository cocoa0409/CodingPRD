"""Freight shipments and rigging bay scheduling (PRD 3.5)."""
from flask import Blueprint

from db import store, new_id, new_common, touch
from errors import ApiError
from middleware import (get_context, require_roles, check_customer_scope,
                        owning_customer_id_of_order, ALL_ROLES)
from response import ok, created, paginate
from services import pricing, workflow
from validation import parse_body, no_body, require_path_entity, schema_field

bp = Blueprint("shipments", __name__)

DIRECTIONS = ["INBOUND", "OUTBOUND"]
SHIPMENT_READ_ROLES = ["IntakeCoordinator", "RemanEngineer", "QualityInspector",
                       "ServiceManager"]


def _load_shipment(shipment_id):
    return require_path_entity(store.shipments, shipment_id)


def _require_state(shipment, allowed):
    if shipment["status"] not in allowed:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Shipment status %s does not admit this action"
                       % shipment["status"])


@bp.post("/reman/orders/<order_id>/shipments")
def create_shipment(order_id):
    uid, role, _ = get_context()
    require_roles(["IntakeCoordinator"])
    order = require_path_entity(store.orders, order_id)
    body = parse_body({
        "direction": schema_field("enum", enum=DIRECTIONS),
        "weight_kg": schema_field("integer"),
        "rigging_bay_date": schema_field("date"),
        "rigging_bay_hours": schema_field("integer"),
    }, allow_empty=False)
    if order["status"] in workflow.ORDER_TERMINAL:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "A %s order is locked against any further action"
                       % order["status"])
    if workflow.rigging_bay_conflicts(body["rigging_bay_date"],
                                      body["rigging_bay_hours"]):
        raise ApiError("ERR_RIGGING_BAY_CONFLICT", 409,
                       "Rigging bay occupancy intersects another non-cancelled "
                       "shipment (including the turnaround buffer tail)")
    shipment = {
        "id": new_id(),
        "reman_order_id": order["id"],
        "direction": body["direction"],
        "weight_kg": body["weight_kg"],
        "rigging_bay_date": body["rigging_bay_date"],
        "rigging_bay_hours": body["rigging_bay_hours"],
        "freight_charge_cents": pricing.freight_charge_cents(
            body["weight_kg"], body["rigging_bay_hours"]),
        "status": "BOOKED",
    }
    new_common(shipment)
    store.shipments[shipment["id"]] = shipment
    return created(shipment)


@bp.get("/reman/orders/<order_id>/shipments")
def list_shipments(order_id):
    uid, role, _ = get_context()
    require_roles(ALL_ROLES)
    order = require_path_entity(store.orders, order_id)
    check_customer_scope(uid, role, owning_customer_id_of_order(order))
    return ok(paginate(workflow.shipments_of_order(order_id)),
              rtype="array", pagination=paginate)


@bp.get("/reman/shipments/<shipment_id>")
def get_shipment(shipment_id):
    uid, role, _ = get_context()
    require_roles(SHIPMENT_READ_ROLES)
    return ok(_load_shipment(shipment_id))


@bp.post("/reman/shipments/<shipment_id>/dispatch")
def dispatch_shipment(shipment_id):
    uid, role, _ = get_context()
    require_roles(["IntakeCoordinator"])
    shipment = _load_shipment(shipment_id)
    no_body()
    _require_state(shipment, ["BOOKED"])
    shipment["status"] = "IN_TRANSIT"
    touch(shipment)
    return ok(shipment)


@bp.post("/reman/shipments/<shipment_id>/deliver")
def deliver_shipment(shipment_id):
    uid, role, _ = get_context()
    require_roles(["IntakeCoordinator"])
    shipment = _load_shipment(shipment_id)
    no_body()
    _require_state(shipment, ["IN_TRANSIT"])
    shipment["status"] = "DELIVERED"
    touch(shipment)
    return ok(shipment)


@bp.post("/reman/shipments/<shipment_id>/cancel")
def cancel_shipment(shipment_id):
    uid, role, _ = get_context()
    require_roles(["IntakeCoordinator"])
    shipment = _load_shipment(shipment_id)
    no_body()
    _require_state(shipment, ["BOOKED"])
    shipment["status"] = "CANCELLED"
    touch(shipment)
    return ok(shipment)
