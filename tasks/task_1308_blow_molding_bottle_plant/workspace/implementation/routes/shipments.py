from flask import Blueprint

from auth import authenticate, require_role
from db import store
from envelope import success_object, success_list
from errors import raise_err, ERR_SHIPMENT_NOT_FOUND, \
    ERR_PRODUCTION_ORDER_NOT_FOUND, ERR_DOCK_APPOINTMENT_NOT_FOUND, \
    ERR_INVALID_STATE, ERR_ALREADY_TERMINAL, ERR_ZERO_QUANTITY, \
    ERR_MODE_MISMATCH, ERR_APPOINTMENT_NOT_RESERVED, \
    ERR_OUTSIDE_DOCK_WINDOW, ERR_INSUFFICIENT_ACCEPTED_STOCK
from calc import freight_compute
from services import stamp_new, touch, ser_shipment, sorted_rows, \
    order_rollups
from util import new_id, logical_now
from validate import get_body, check_fields, pagination_params, query_filter
from routes.freight import require_active_card

bp = Blueprint("shipments", __name__)

READ_ROLES = ["PlantAdmin", "ProductionScheduler", "LogisticsCoordinator"]
SHIPMENT_STATUSES = {"QUOTED", "BOOKED", "LOADING", "IN_TRANSIT",
                     "DELIVERED", "CANCELLED"}
TERMINAL = ("DELIVERED", "CANCELLED")
MODE_FOR_LOGISTICS = {"WAREHOUSE": "FINISHED_BOTTLES",
                      "BLOW_ON_SITE": "PREFORMS"}


def get_shipment_or_404(shipment_id):
    s = store.shipments.get(shipment_id)
    if s is None:
        raise_err(ERR_SHIPMENT_NOT_FOUND, "Shipment id does not resolve")
    return s


def _check_terminal(shipment):
    if shipment["status"] in TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "Shipment is in a terminal state")


@bp.post("/shipments")
def create_shipment():
    _, role = authenticate()
    require_role(role, ["LogisticsCoordinator"])
    body = check_fields(get_body(), {
        "production_order_id": ("str", True),
        "quantity": ("number", True),
        "shipment_mode": ("enum", True, {"FINISHED_BOTTLES", "PREFORMS"}),
    })
    order = store.production_orders.get(body["production_order_id"])
    if order is None:
        raise_err(ERR_PRODUCTION_ORDER_NOT_FOUND,
                  "ProductionOrder id does not resolve")
    card = require_active_card()
    if order["status"] not in ("RUNNING", "HELD", "COMPLETED"):
        raise_err(ERR_INVALID_STATE,
                  "Order must be RUNNING, HELD or COMPLETED to ship")
    quantity = body["quantity"]
    if quantity != int(quantity) or quantity <= 0:
        raise_err(ERR_ZERO_QUANTITY,
                  "Shipment quantity must be a positive integer")
    quantity = int(quantity)
    if MODE_FOR_LOGISTICS[order["logistics_mode"]] != body["shipment_mode"]:
        raise_err(ERR_MODE_MISMATCH,
                  "shipment_mode is inconsistent with order.logistics_mode")
    spec = store.bottle_specs.get(order["bottle_spec_id"])
    result = freight_compute(spec, quantity, body["shipment_mode"],
                             card["tiers"])
    shipment = {
        "production_order_id": order["id"],
        "customer_id": order["customer_id"],
        "shipment_mode": body["shipment_mode"],
        "quantity": quantity,
        "pallets": result["pallets"],
        "volume_cm3": result["volume_cm3"],
        "dim_weight_kg": result["dim_weight_kg"],
        "actual_weight_kg": result["actual_weight_kg"],
        "chargeable_weight_kg": result["chargeable_weight_kg"],
        "freight_cost_cents": result["freight_cost_cents"],
        "booked_appointment_id": None,
        "status": "QUOTED",
    }
    stamp_new(shipment, new_id())
    store.shipments[shipment["id"]] = shipment
    return success_object(ser_shipment(shipment), 201)


@bp.get("/shipments")
def list_shipments():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    production_order_id = query_filter("production_order_id")
    customer_id = query_filter("customer_id")
    status = query_filter("status", SHIPMENT_STATUSES)
    limit, offset = pagination_params()
    rows = list(store.shipments.values())
    if production_order_id is not None:
        rows = [s for s in rows if s["production_order_id"] == production_order_id]
    if customer_id is not None:
        rows = [s for s in rows if s["customer_id"] == customer_id]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    rows = sorted_rows(rows)
    page = rows[offset:offset + limit]
    return success_list([ser_shipment(s) for s in page], limit, offset,
                        len(rows))


@bp.get("/shipments/<sid>")
def get_shipment(sid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    return success_object(ser_shipment(get_shipment_or_404(sid)))


@bp.post("/shipments/<sid>/book")
def book_shipment(sid):
    _, role = authenticate()
    require_role(role, ["LogisticsCoordinator"])
    body = check_fields(get_body(), {"dock_appointment_id": ("str", True)})
    shipment = get_shipment_or_404(sid)
    appt = store.dock_appointments.get(body["dock_appointment_id"])
    if appt is None:
        raise_err(ERR_DOCK_APPOINTMENT_NOT_FOUND,
                  "DockAppointment id does not resolve")
    _check_terminal(shipment)
    if shipment["status"] != "QUOTED":
        raise_err(ERR_INVALID_STATE, "Only a QUOTED shipment can be booked")
    if appt["status"] != "RESERVED" or appt["shipment_id"] != shipment["id"]:
        raise_err(ERR_APPOINTMENT_NOT_RESERVED,
                  "Dock appointment is not RESERVED for this shipment")
    order = store.production_orders.get(shipment["production_order_id"])
    unallocated = order_rollups(order)["quantity_unallocated"]
    if shipment["quantity"] > unallocated:
        raise_err(ERR_INSUFFICIENT_ACCEPTED_STOCK,
                  "Shipment quantity exceeds quantity_unallocated")
    shipment["booked_appointment_id"] = appt["id"]
    shipment["status"] = "BOOKED"
    touch(shipment)
    return success_object(ser_shipment(shipment))


@bp.post("/shipments/<sid>/load")
def load_shipment(sid):
    _, role = authenticate()
    require_role(role, ["LogisticsCoordinator"])
    check_fields(get_body(), {})
    shipment = get_shipment_or_404(sid)
    _check_terminal(shipment)
    if shipment["status"] != "BOOKED":
        raise_err(ERR_INVALID_STATE, "Only a BOOKED shipment can load")
    appt = store.dock_appointments.get(shipment["booked_appointment_id"])
    if appt is None or appt["status"] != "RESERVED":
        raise_err(ERR_APPOINTMENT_NOT_RESERVED,
                  "Booked appointment is not RESERVED")
    now = logical_now()
    if not (appt["window_start"] <= now <= appt["window_end"]):
        raise_err(ERR_OUTSIDE_DOCK_WINDOW,
                  "Current clock is outside the booked dock window")
    appt["status"] = "OCCUPIED"
    touch(appt)
    shipment["status"] = "LOADING"
    touch(shipment)
    return success_object(ser_shipment(shipment))


@bp.post("/shipments/<sid>/dispatch")
def dispatch_shipment(sid):
    _, role = authenticate()
    require_role(role, ["LogisticsCoordinator"])
    check_fields(get_body(), {})
    shipment = get_shipment_or_404(sid)
    _check_terminal(shipment)
    if shipment["status"] != "LOADING":
        raise_err(ERR_INVALID_STATE, "Only a LOADING shipment can dispatch")
    shipment["status"] = "IN_TRANSIT"
    touch(shipment)
    return success_object(ser_shipment(shipment))


@bp.post("/shipments/<sid>/deliver")
def deliver_shipment(sid):
    _, role = authenticate()
    require_role(role, ["LogisticsCoordinator"])
    check_fields(get_body(), {})
    shipment = get_shipment_or_404(sid)
    _check_terminal(shipment)
    if shipment["status"] != "IN_TRANSIT":
        raise_err(ERR_INVALID_STATE,
                  "Only an IN_TRANSIT shipment can be delivered")
    appt = store.dock_appointments.get(shipment["booked_appointment_id"])
    if appt is not None and appt["status"] == "OCCUPIED":
        appt["status"] = "COMPLETED"
        touch(appt)
    shipment["status"] = "DELIVERED"
    touch(shipment)
    return success_object(ser_shipment(shipment))


@bp.post("/shipments/<sid>/cancel")
def cancel_shipment(sid):
    _, role = authenticate()
    require_role(role, ["LogisticsCoordinator"])
    check_fields(get_body(), {})
    shipment = get_shipment_or_404(sid)
    _check_terminal(shipment)
    if shipment["status"] not in ("QUOTED", "BOOKED"):
        raise_err(ERR_INVALID_STATE,
                  "Only a QUOTED or BOOKED shipment can be cancelled")
    if shipment["status"] == "BOOKED":
        appt = store.dock_appointments.get(shipment["booked_appointment_id"])
        if appt is not None and appt["status"] == "RESERVED":
            appt["status"] = "CANCELLED"
            touch(appt)
        shipment["booked_appointment_id"] = None
    shipment["status"] = "CANCELLED"
    touch(shipment)
    return success_object(ser_shipment(shipment))
