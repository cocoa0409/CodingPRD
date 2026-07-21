from datetime import timedelta

from flask import Blueprint, request

import store
from calc import planned_days, late_fee, RENTAL_BUFFER_SECONDS
from common import (
    authorize, get_json, need, as_str,
    require_found, check_owner, parse_pagination, paginate,
)
from envelope import object_response, array_response
from errors import err
from timeutil import parse_dt

bp = Blueprint("rentals", __name__)

_BUFFER = timedelta(seconds=RENTAL_BUFFER_SECONDS)
ACTIVE_RENTAL = ("RESERVED", "CHECKED_OUT")


def _parse_or_400(value, name):
    try:
        return parse_dt(value)
    except (ValueError, TypeError):
        raise err("ERR_VALIDATION", name + " must be an ISO 8601 instant")


@bp.post("/rentals")
def create_rental():
    _, role = authorize(["Member", "Clerk", "Manager"])
    body = get_json()
    mid = body.get("member_id")
    if mid is not None and mid not in store.members:
        raise err("ERR_NOT_FOUND", "member_id does not exist")
    iid = body.get("inventory_item_id")
    if iid is not None and iid not in store.inventory_items:
        raise err("ERR_NOT_FOUND", "inventory_item_id does not exist")
    member_id = need(body, "member_id")
    inventory_item_id = need(body, "inventory_item_id")
    start_raw = as_str(need(body, "start_at"), "start_at")
    due_raw = as_str(need(body, "due_at"), "due_at")
    start_dt = _parse_or_400(start_raw, "start_at")
    due_dt = _parse_or_400(due_raw, "due_at")
    if not (due_dt > start_dt):
        raise err("ERR_VALIDATION", "due_at must be strictly after start_at")
    check_owner(role, request.headers.get("X-User-ID"), member_id)
    # Overlap protection with a 24h buffer against active rentals on the same item.
    for other in store.rentals.values():
        if other["inventory_item_id"] != inventory_item_id:
            continue
        if other["status"] not in ACTIVE_RENTAL:
            continue
        o_start = parse_dt(other["start_at"])
        o_due = parse_dt(other["due_at"])
        if start_dt < (o_due + _BUFFER) and o_start < (due_dt + _BUFFER):
            raise err("ERR_RENTAL_OVERLAP", "Rental interval collides with an active rental")
    item = store.inventory_items[inventory_item_id]
    product = store.products[item["product_id"]]
    daily_rate = product["daily_rental_rate_cents"]
    r = store.make_record({
        "member_id": member_id,
        "inventory_item_id": inventory_item_id,
        "start_at": start_raw,
        "due_at": due_raw,
        "daily_rate_cents": daily_rate,
        "planned_days": planned_days(start_dt, due_dt),
        "returned_at": None,
        "estimated_charge_cents": None,
        "late_fee_cents": 0,
        "final_charge_cents": None,
        "status": "RESERVED",
    })
    store.rentals[r["id"]] = r
    return object_response(store.serialize(r), 201)


@bp.get("/rentals/<rid>")
def get_rental(rid):
    authorize(["Member", "Clerk", "Manager"])
    r = require_found(store.rentals, rid)
    return object_response(store.serialize(r), 200)


@bp.get("/rentals")
def list_rentals():
    authorize(["Member", "Clerk", "Manager"])
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    inventory_item_id = request.args.get("inventory_item_id")
    matching = list(store.rentals.values())
    if member_id is not None:
        matching = [r for r in matching if r["member_id"] == member_id]
    if inventory_item_id is not None:
        matching = [r for r in matching if r["inventory_item_id"] == inventory_item_id]
    window, total = paginate(matching, limit, offset)
    return array_response([store.serialize(r) for r in window], limit, offset, total)


@bp.post("/rentals/<rid>/checkout")
def checkout(rid):
    authorize(["Clerk", "Manager"])
    r = require_found(store.rentals, rid)
    if r["status"] != "RESERVED":
        raise err("ERR_INVALID_STATE", "Only a RESERVED rental can be checked out")
    item = store.inventory_items[r["inventory_item_id"]]
    if item["status"] != "AVAILABLE":
        raise err("ERR_ITEM_NOT_AVAILABLE", "Inventory item is not AVAILABLE")
    item["status"] = "RENTED"
    store.touch(item)
    r["status"] = "CHECKED_OUT"
    r["estimated_charge_cents"] = r["daily_rate_cents"] * r["planned_days"]
    store.touch(r)
    return object_response(store.serialize(r), 200)


@bp.post("/rentals/<rid>/return")
def return_rental(rid):
    authorize(["Clerk", "Manager"])
    r = require_found(store.rentals, rid)
    if r["status"] != "CHECKED_OUT":
        raise err("ERR_INVALID_STATE", "Only a CHECKED_OUT rental can be returned")
    returned_dt = store.clock_dt()
    due_dt = parse_dt(r["due_at"])
    fee = late_fee(returned_dt, due_dt)
    r["returned_at"] = store.clock_raw()
    r["late_fee_cents"] = fee
    r["final_charge_cents"] = r["estimated_charge_cents"] + fee
    r["status"] = "RETURNED"
    item = store.inventory_items[r["inventory_item_id"]]
    item["status"] = "AVAILABLE"
    store.touch(item)
    store.touch(r)
    return object_response(store.serialize(r), 200)
