"""Routes: shipping racks and rack reservations."""
from datetime import timedelta

from flask import Blueprint, request

from common import (ANY_ROLE, ApiError, body_json, list_response, need, obj_response,
                    paginate, require_roles, v_dt, v_int, v_str)
from services import (get_or_404, lines_of_order, live_lines, rack_recompute, ser_rack,
                      ser_resv, transition_line)
from store import STORE, new_entity, touch

bp_shipping = Blueprint("shipping", __name__)


@bp_shipping.post("/fenestration/shipping-racks")
@require_roles("ShippingCoordinator", "PlantManager")
def create_rack():
    body = body_json()
    r = new_entity({
        "rack_code": v_str(need(body, "rack_code"), "rack_code"),
        "slot_capacity": v_int(need(body, "slot_capacity"), "slot_capacity"),
        "status": "AVAILABLE",
    })
    STORE.racks[r["id"]] = r
    return obj_response(ser_rack(r), 201)


@bp_shipping.get("/fenestration/shipping-racks/<rackId>")
@require_roles(*ANY_ROLE)
def get_rack(rackId):
    return obj_response(ser_rack(get_or_404(STORE.racks, rackId)), 200)


@bp_shipping.get("/fenestration/shipping-racks")
@require_roles(*ANY_ROLE)
def list_racks():
    items = list(STORE.racks.values())
    val = request.args.get("status")
    if val is not None:
        items = [r for r in items if r["status"] == val]
    page, limit, offset, total = paginate(items)
    return list_response([ser_rack(r) for r in page], limit, offset, total)


# ------------------------------------------------------------------ reservations

@bp_shipping.post("/fenestration/shipping-racks/<rackId>/reservations")
@require_roles("ShippingCoordinator", "PlantManager")
def create_reservation(rackId):
    rack = get_or_404(STORE.racks, rackId)
    body = body_json()
    order_id = v_str(need(body, "order_id"), "order_id")
    order = get_or_404(STORE.orders, order_id)
    load_date = v_dt(need(body, "load_date"), "load_date")
    ship_date = v_dt(need(body, "ship_date"), "ship_date")
    if order["production_status"] not in ("IN_PROGRESS", "COMPLETED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Reservation order must be IN_PROGRESS or COMPLETED")
    # Closed-interval occupancy + 1-day turnover buffer:
    # conflict iff NOT (l2 > s1 + 1d OR l1 > s2 + 1d).
    day = timedelta(days=1)
    for r in STORE.reservations.values():
        if r["rack_id"] != rack["id"] or r["status"] not in ("RESERVED", "LOADING"):
            continue
        if not (load_date > r["ship_date"] + day or r["load_date"] > ship_date + day):
            raise ApiError("ERR_RACK_OCCUPANCY_CONFLICT", 409,
                           "Reservation window conflicts with an active reservation")
    resv = new_entity({
        "rack_id": rack["id"], "order_id": order["id"],
        "load_date": load_date, "ship_date": ship_date,
        "assigned_units": 0, "status": "RESERVED",
    })
    STORE.reservations[resv["id"]] = resv
    rack_recompute(rack)
    return obj_response(ser_resv(resv), 201)


@bp_shipping.get("/fenestration/shipping-racks/<rackId>/reservations")
@require_roles(*ANY_ROLE)
def list_rack_reservations(rackId):
    get_or_404(STORE.racks, rackId)
    items = [r for r in STORE.reservations.values() if r["rack_id"] == rackId]
    page, limit, offset, total = paginate(items)
    return list_response([ser_resv(r) for r in page], limit, offset, total)


@bp_shipping.get("/fenestration/rack-reservations/<reservationId>")
@require_roles(*ANY_ROLE)
def get_reservation(reservationId):
    return obj_response(ser_resv(get_or_404(STORE.reservations, reservationId)), 200)


@bp_shipping.get("/fenestration/rack-reservations")
@require_roles(*ANY_ROLE)
def list_reservations():
    items = list(STORE.reservations.values())
    for param in ("order_id", "rack_id"):
        val = request.args.get(param)
        if val is not None:
            items = [r for r in items if str(r.get(param)) == val]
    page, limit, offset, total = paginate(items)
    return list_response([ser_resv(r) for r in page], limit, offset, total)


@bp_shipping.post("/fenestration/rack-reservations/<reservationId>/load")
@require_roles("ShippingCoordinator", "PlantManager")
def load_reservation(reservationId):
    resv = get_or_404(STORE.reservations, reservationId)
    body = body_json()
    line_id = v_str(need(body, "order_line_id"), "order_line_id")
    line = get_or_404(STORE.lines, line_id)
    if resv["status"] not in ("RESERVED", "LOADING"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Reservation in {resv['status']} cannot be loaded")
    if line["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a COMPLETED line can be loaded")
    if line["order_id"] != resv["order_id"]:
        raise ApiError("ERR_RACK_WRONG_ORDER", 409,
                       "Line does not belong to the reservation's order")
    if line["rack_id"] is not None:
        raise ApiError("ERR_INVALID_STATE", 409, "Line is already loaded on a rack")
    rack = STORE.racks.get(resv["rack_id"])
    if resv["assigned_units"] + line["quantity"] > rack["slot_capacity"]:
        raise ApiError("ERR_RACK_CAPACITY_EXCEEDED", 409,
                       "Load would exceed rack slot capacity")
    line["rack_id"] = resv["rack_id"]
    touch(line)
    resv["assigned_units"] += line["quantity"]
    if resv["status"] == "RESERVED":
        resv["status"] = "LOADING"
    touch(resv)
    return obj_response(ser_resv(resv), 200)


@bp_shipping.post("/fenestration/rack-reservations/<reservationId>/ship")
@require_roles("ShippingCoordinator", "PlantManager")
def ship_reservation(reservationId):
    resv = get_or_404(STORE.reservations, reservationId)
    if resv["status"] != "LOADING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a LOADING reservation can be shipped")
    order = STORE.orders.get(resv["order_id"])
    if order is None or order["production_status"] != "COMPLETED":
        raise ApiError("ERR_ORDER_NOT_SHIPPABLE", 409,
                       "Reservation's order is not COMPLETED")
    resv["status"] = "SHIPPED"
    touch(resv)
    for line in lines_of_order(order["id"]):
        if line["rack_id"] == resv["rack_id"] and line["status"] == "COMPLETED":
            transition_line(line, "SHIPPED")
    # Bubble-up: all non-CANCELLED lines SHIPPED -> order SHIPPED.
    remaining = [l for l in live_lines(order["id"]) if l["status"] != "SHIPPED"]
    if not remaining and order["production_status"] == "COMPLETED":
        order["production_status"] = "SHIPPED"
        touch(order)
    rack = STORE.racks.get(resv["rack_id"])
    if rack:
        rack_recompute(rack)
    return obj_response(ser_resv(resv), 200)


@bp_shipping.post("/fenestration/rack-reservations/<reservationId>/cancel")
@require_roles("ShippingCoordinator", "PlantManager")
def cancel_reservation(reservationId):
    resv = get_or_404(STORE.reservations, reservationId)
    if resv["status"] != "RESERVED" or resv["assigned_units"] != 0:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an un-loaded RESERVED reservation can be cancelled")
    resv["status"] = "CANCELLED"
    touch(resv)
    rack = STORE.racks.get(resv["rack_id"])
    if rack:
        rack_recompute(rack)
    return obj_response(ser_resv(resv), 200)
