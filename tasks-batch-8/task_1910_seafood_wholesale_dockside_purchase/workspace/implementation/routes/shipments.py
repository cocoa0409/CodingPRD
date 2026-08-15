"""Shipment: cold-chain truck and air freight with pinned freight tariff."""
from decimal import Decimal

from flask import Blueprint

from db import store, new_record, touch
from errors import (
    ApiError,
    ERR_SHIPMENT_NOT_FOUND,
    ERR_ORDER_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_ORDER_INVALID_STATE,
    ERR_SHIPMENT_INVALID_STATE,
    ERR_FLIGHT_CAPACITY_EXCEEDED,
)
from middleware import auth, require
from response import ok, ok_list
from services.calc import ZERO, q2, freight_charge_cents, dimensional_weight_kg
from services.cascades import deplete_check, order_lines_of
from util import body, req_str, req_enum, opt_str, req_num, req_date, parse_date_str, apply_filters

bp = Blueprint("shipments", __name__)

MODES = {"AIR", "TRUCK"}
TEMP_ZONES = {"CHILLED", "FROZEN"}
FLIGHT_CAPACITY_KG = Decimal("1000")
CAPACITY_STATES = ("BOOKED", "TENDERED", "IN_TRANSIT")


def _get_shipment(rid):
    rec = store.shipments.get(rid)
    if rec is None:
        raise ApiError(ERR_SHIPMENT_NOT_FOUND, 404, "Shipment id does not exist")
    return rec


@bp.post("/shipments")
def create_shipment():
    _, role = auth()
    require(role, {"LogisticsCoordinator"})
    b = body()
    sales_order_id = req_str(b, "sales_order_id")
    mode = req_enum(b, "mode", MODES)
    booked_weight_kg = req_num(b, "booked_weight_kg")
    if booked_weight_kg <= ZERO:
        raise ApiError(ERR_INVALID_REQUEST, 400, "booked_weight_kg must be > 0")
    temp_zone = req_enum(b, "temp_zone", TEMP_ZONES)
    flight_number = opt_str(b, "flight_number", "")
    flight_date = opt_str(b, "flight_date", "")
    if mode == "AIR":
        # Air freight requires both flight fields; absence is a shape failure.
        if not flight_number or not flight_date or parse_date_str(flight_date) is None:
            raise ApiError(
                ERR_INVALID_REQUEST, 400,
                "flight_number and flight_date (YYYY-MM-DD) are required for AIR",
            )
    elif flight_date:
        if parse_date_str(flight_date) is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, "flight_date must be YYYY-MM-DD")
    order = store.orders.get(sales_order_id)
    if order is None:
        raise ApiError(ERR_ORDER_NOT_FOUND, 404, "SalesOrder id does not exist")
    if order["status"] not in ("CONFIRMED", "FULFILLED"):
        raise ApiError(
            ERR_ORDER_INVALID_STATE, 409,
            "Shipments require a CONFIRMED or FULFILLED order",
        )
    rec = new_record({
        "sales_order_id": sales_order_id,
        "mode": mode,
        "flight_number": flight_number,
        "flight_date": flight_date,
        "temp_zone": temp_zone,
        "booked_weight_kg": q2(booked_weight_kg),
        "actual_weight_kg": ZERO,
        "volume_m3": ZERO,
        "chargeable_weight_kg": ZERO,
        "provisional_freight_cents": 0,
        "final_freight_cents": 0,
        "status": "QUOTED",
    })
    store.shipments[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/shipments")
def list_shipments():
    auth()
    page, total, limit, offset = apply_filters(
        list(store.shipments.values()),
        ["sales_order_id", "status"],
    )
    return ok_list(page, total, limit, offset)


@bp.get("/shipments/<rid>")
def get_shipment(rid):
    auth()
    return ok(_get_shipment(rid))


@bp.post("/shipments/<rid>/book")
def book_shipment(rid):
    _, role = auth()
    require(role, {"LogisticsCoordinator"})
    shipment = _get_shipment(rid)
    if shipment["status"] != "QUOTED":
        raise ApiError(ERR_SHIPMENT_INVALID_STATE, 409, "Shipment is not in QUOTED")
    if shipment["mode"] == "AIR":
        booked_total = sum(
            (s["booked_weight_kg"] for s in store.shipments.values()
             if s["id"] != shipment["id"]
             and s["mode"] == "AIR"
             and s["status"] in CAPACITY_STATES
             and s["flight_number"] == shipment["flight_number"]
             and s["flight_date"] == shipment["flight_date"]),
            ZERO,
        )
        if booked_total + shipment["booked_weight_kg"] > FLIGHT_CAPACITY_KG:
            raise ApiError(
                ERR_FLIGHT_CAPACITY_EXCEEDED, 409,
                "AIR booking would exceed 1000 kg on this flight",
            )
    # Provisional variant: chargeable = booked weight (no dimensional term).
    shipment["chargeable_weight_kg"] = shipment["booked_weight_kg"]
    shipment["provisional_freight_cents"] = freight_charge_cents(
        shipment["mode"], shipment["chargeable_weight_kg"]
    )
    shipment["status"] = "BOOKED"
    touch(shipment)
    return ok(shipment)


@bp.post("/shipments/<rid>/tender")
def tender_shipment(rid):
    _, role = auth()
    require(role, {"LogisticsCoordinator"})
    b = body()
    actual_weight_kg = req_num(b, "actual_weight_kg")
    if actual_weight_kg <= ZERO:
        raise ApiError(ERR_INVALID_REQUEST, 400, "actual_weight_kg must be > 0")
    volume_m3 = req_num(b, "volume_m3")
    if volume_m3 < ZERO:
        raise ApiError(ERR_INVALID_REQUEST, 400, "volume_m3 must be >= 0")
    shipment = _get_shipment(rid)
    if shipment["status"] != "BOOKED":
        raise ApiError(ERR_SHIPMENT_INVALID_STATE, 409, "Shipment is not in BOOKED")
    actual = q2(actual_weight_kg)
    volume = q2(volume_m3)
    # Final variant: chargeable = max(actual, dimensional).
    chargeable = max(actual, dimensional_weight_kg(volume))
    shipment["actual_weight_kg"] = actual
    shipment["volume_m3"] = volume
    shipment["chargeable_weight_kg"] = chargeable
    shipment["final_freight_cents"] = freight_charge_cents(shipment["mode"], chargeable)
    shipment["status"] = "TENDERED"
    touch(shipment)
    return ok(shipment)


@bp.post("/shipments/<rid>/depart")
def depart_shipment(rid):
    _, role = auth()
    require(role, {"LogisticsCoordinator"})
    shipment = _get_shipment(rid)
    if shipment["status"] != "TENDERED":
        raise ApiError(ERR_SHIPMENT_INVALID_STATE, 409, "Shipment is not in TENDERED")
    shipment["status"] = "IN_TRANSIT"
    touch(shipment)
    return ok(shipment)


@bp.post("/shipments/<rid>/deliver")
def deliver_shipment(rid):
    _, role = auth()
    require(role, {"LogisticsCoordinator"})
    shipment = _get_shipment(rid)
    if shipment["status"] != "IN_TRANSIT":
        raise ApiError(ERR_SHIPMENT_INVALID_STATE, 409, "Shipment is not in IN_TRANSIT")
    # Physical settlement: every COMMITTED allocation on the order's lines
    # moves its weight from the lot's committed bucket into shipped.
    touched_lots = set()
    for line in order_lines_of(shipment["sales_order_id"]):
        for alloc in store.allocations.values():
            if alloc["order_line_id"] == line["id"] and alloc["status"] == "COMMITTED":
                lot = store.lots[alloc["inventory_lot_id"]]
                lot["committed_weight_kg"] -= alloc["qty_kg"]
                lot["shipped_weight_kg"] += alloc["qty_kg"]
                touched_lots.add(lot["id"])
    for lot_id in touched_lots:
        lot = store.lots[lot_id]
        deplete_check(lot)
        touch(lot)
    shipment["status"] = "DELIVERED"
    touch(shipment)
    return ok(shipment)


@bp.post("/shipments/<rid>/cancel")
def cancel_shipment(rid):
    _, role = auth()
    require(role, {"LogisticsCoordinator"})
    shipment = _get_shipment(rid)
    if shipment["status"] not in ("QUOTED", "BOOKED"):
        raise ApiError(
            ERR_SHIPMENT_INVALID_STATE, 409,
            "Shipment cannot be cancelled from %s" % shipment["status"],
        )
    shipment["status"] = "CANCELLED"
    touch(shipment)
    return ok(shipment)
