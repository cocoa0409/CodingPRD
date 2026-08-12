"""SlotReservation endpoints: create (auto QR label), get/list, release, consume."""

from flask import Blueprint, request

import db
from db import store, stamp, touch
from errors import ApiError, invalid_state, already_terminal
from services import (
    SIZE_CEILING_CM, ORDER_TERMINAL, SLOT_HOLD,
    ser_reservation, get_or_404, order_items, issue_label,
    held_reservation, release_reservation,
)
from util import require_roles, respond, body, req_str, paginate

bp = Blueprint("reservations", __name__)


def _own_reservation_order(uid, role, res):
    order = store["orders"][res["return_order_id"]]
    if role == "Shopper" and order["shopper_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "Shopper may act only on its own orders")
    if role == "LocationOperator":
        slot = store["slots"][res["slot_id"]]
        if slot["location_id"] != uid:
            raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                           "LocationOperator may act only at its own location")


@bp.post("/slot-reservations")
def create_reservation():
    uid, role = require_roles("Shopper")
    b = body(required=True)
    order_id = req_str(b, "return_order_id")
    slot_id = req_str(b, "slot_id")
    order = get_or_404("orders", order_id)
    slot = get_or_404("slots", slot_id)
    if order["shopper_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "Shopper may reserve slots only for its own orders")
    # Priority 6: order from-state and slot service state.
    if order["status"] in ORDER_TERMINAL:
        already_terminal("Order is in a terminal state")
    if order["status"] != "INITIATED":
        invalid_state("Reservation requires an INITIATED order")
    if order["method"] != "LOCKER_QR":
        invalid_state("Reservation requires method LOCKER_QR")
    if slot["status"] == "OUT_OF_SERVICE":
        raise ApiError("ERR_SLOT_OUT_OF_SERVICE", 409, "Slot is OUT_OF_SERVICE")
    if slot["status"] == "OCCUPIED":
        raise ApiError("ERR_SLOT_UNAVAILABLE", 409, "Slot is occupied")
    # Priority 9: size-class fit against the order's largest item.
    items = order_items(order_id)
    max_side = max([i["longest_side_cm"] for i in items], default=0)
    if max_side > SIZE_CEILING_CM[slot["size_class"]]:
        raise ApiError("ERR_SLOT_SIZE_TOO_SMALL", 422,
                       "Slot size_class cannot fit the order's largest item")
    # Priority 11: location OPERATIONAL, then live-hold exclusivity.
    location = store["locations"][slot["location_id"]]
    if location["status"] != "OPERATIONAL":
        raise ApiError("ERR_LOCATION_NOT_OPERATIONAL", 409,
                       "Location is not OPERATIONAL")
    now = db.now()
    for r in store["reservations"].values():
        if r["slot_id"] == slot_id and r["status"] == "HELD" and r["hold_until"] > now:
            raise ApiError("ERR_SLOT_UNAVAILABLE", 409,
                           "Slot has a live HELD reservation")
    res = {
        "slot_id": slot_id,
        "return_order_id": order_id,
        "status": "HELD",
        "hold_start": now,
        "hold_until": now + SLOT_HOLD,
        "label_id": None,
    }
    stamp(res)
    store["reservations"][res["id"]] = res
    slot["status"] = "RESERVED"
    touch(slot)
    label = issue_label(order, "QR_CODE", supersedes=None)
    res["label_id"] = label["id"]
    touch(res)
    order["status"] = "LABEL_ISSUED"
    touch(order)
    return respond(ser_reservation(res), 201)


@bp.get("/slot-reservations/<rid>")
def get_reservation(rid):
    uid, role = require_roles("Shopper", "LocationOperator", "SupportAgent",
                              "PlatformAdmin")
    res = get_or_404("reservations", rid)
    _own_reservation_order(uid, role, res)
    return respond(ser_reservation(res))


@bp.get("/slot-reservations")
def list_reservations():
    require_roles("LocationOperator", "SupportAgent", "PlatformAdmin")
    items = list(store["reservations"].values())
    slot_id = request.args.get("slot_id")
    order_id = request.args.get("return_order_id")
    label_id = request.args.get("label_id")
    status = request.args.get("status")
    if slot_id is not None:
        items = [r for r in items if r["slot_id"] == slot_id]
    if order_id is not None:
        items = [r for r in items if r["return_order_id"] == order_id]
    if label_id is not None:
        items = [r for r in items if r.get("label_id") == label_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, meta = paginate(items)
    return respond([ser_reservation(r) for r in page], page=meta)


@bp.post("/slot-reservations/<rid>/release")
def release_reservation_endpoint(rid):
    uid, role = require_roles("Shopper", "LocationOperator")
    res = get_or_404("reservations", rid)
    _own_reservation_order(uid, role, res)
    if res["status"] != "HELD":
        already_terminal("Reservation is not HELD")
    release_reservation(res)
    order = store["orders"][res["return_order_id"]]
    if order["status"] == "LABEL_ISSUED":
        order["status"] = "INITIATED"
        touch(order)
    return respond(ser_reservation(res))


@bp.post("/slot-reservations/<rid>/consume")
def consume_reservation(rid):
    uid, role = require_roles("LocationOperator")
    res = get_or_404("reservations", rid)
    _own_reservation_order(uid, role, res)
    if res["status"] != "HELD":
        already_terminal("Reservation is not HELD")
    now = db.now()
    # Priority 10: reservation hold, then bound-label expiry.
    if not now < res["hold_until"]:
        raise ApiError("ERR_RESERVATION_EXPIRED", 409,
                       "Consume attempted at or after hold_until")
    label = store["labels"].get(res.get("label_id"))
    if label is not None and label["expires_at"] <= now:
        raise ApiError("ERR_LABEL_EXPIRED", 409,
                       "Consume attempted with an expired label")
    slot = store["slots"][res["slot_id"]]
    order = store["orders"][res["return_order_id"]]
    # Cascade link 1: slot RESERVED -> OCCUPIED.
    if slot["status"] == "RESERVED":
        slot["status"] = "OCCUPIED"
        touch(slot)
    # Link 2: order LABEL_ISSUED -> DROPPED_OFF at the slot's location.
    if order["status"] == "LABEL_ISSUED":
        order["status"] = "DROPPED_OFF"
        order["dropoff_location_id"] = slot["location_id"]
        touch(order)
    # Link 3: bound label ISSUED -> CONSUMED.
    if label is not None and label["status"] == "ISSUED":
        label["status"] = "CONSUMED"
        touch(label)
    res["status"] = "CONSUMED"
    touch(res)
    return respond(ser_reservation(res))
