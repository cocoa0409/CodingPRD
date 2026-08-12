"""PartStock (with OCC adjustment) and PartReservation endpoints."""

from flask import Blueprint

import db
import serializers as ser
import services
from errors import (
    ERR_INSUFFICIENT_STOCK,
    ERR_INVALID_ITEM_STATE,
    ERR_INVALID_RESERVATION_STATE,
    ERR_ITEM_NOT_FOUND,
    ERR_PART_STOCK_NOT_FOUND,
    ERR_RESERVATION_EXPIRED,
    ERR_RESERVATION_NOT_FOUND,
    ERR_SAFETY_HOLD,
    ERR_STALE_VERSION,
    ERR_STOCK_BELOW_RESERVED,
    ERR_VALIDATION,
    raise_err,
)
from middleware import require_roles
from response import success
from util import as_enum, as_int, as_str, body, list_response, opt, req

bp = Blueprint("parts", __name__)

ALL_ROLES = ("Coordinator", "IntakeVolunteer", "Fixer", "SafetyOfficer")
STOCK_CATEGORIES = ("ELECTRONICS", "TEXTILE", "BIKE", "GENERIC")


def get_stock_or_404(stock_id):
    stock = db.stocks.get(stock_id)
    if stock is None:
        raise_err(ERR_PART_STOCK_NOT_FOUND, "PartStock %s does not exist" % stock_id)
    return stock


def get_reservation_or_404(reservation_id):
    rec = db.reservations.get(reservation_id)
    if rec is None:
        raise_err(ERR_RESERVATION_NOT_FOUND, "PartReservation %s does not exist" % reservation_id)
    return rec


# -------------------------------------------------------------- part stocks ---

@bp.post("/api/part-stocks")
@require_roles("Coordinator")
def create_stock():
    b = body()
    sku = as_str(req(b, "sku"), "sku", required_len=True)
    name = as_str(req(b, "name"), "name")
    category = as_enum(req(b, "category"), "category", STOCK_CATEGORIES)
    unit_cost = as_int(req(b, "unit_cost_cents"), "unit_cost_cents", lo=0)
    on_hand = as_int(req(b, "quantity_on_hand"), "quantity_on_hand", lo=0)
    for s in db.stocks.values():
        if s["sku"] == sku:
            raise_err(ERR_VALIDATION, "A part stock with this sku already exists")
    rec = db.stamp_new(
        {
            "sku": sku,
            "name": name,
            "category": category,
            "unit_cost_cents": unit_cost,
            "quantity_on_hand": on_hand,
        }
    )
    db.stocks[rec["id"]] = rec
    return success(ser.stock(rec), 201)


@bp.get("/api/part-stocks")
@require_roles(*ALL_ROLES)
def list_stocks():
    return list_response(
        db.stocks.values(),
        ser.stock,
        [("category", "category"), ("sku", "sku")],
    )


@bp.get("/api/part-stocks/<stock_id>")
@require_roles(*ALL_ROLES)
def get_stock(stock_id):
    return success(ser.stock(get_stock_or_404(stock_id)), 200)


@bp.patch("/api/part-stocks/<stock_id>")
@require_roles("Coordinator")
def adjust_stock(stock_id):
    stock = get_stock_or_404(stock_id)
    b = body()
    expected = as_int(req(b, "expected_part_stock_version"), "expected_part_stock_version")
    new_on_hand = opt(b, "quantity_on_hand")
    if new_on_hand is not None:
        as_int(new_on_hand, "quantity_on_hand", lo=0)
    new_cost = opt(b, "unit_cost_cents")
    if new_cost is not None:
        as_int(new_cost, "unit_cost_cents", lo=0)
    # OCC: expected_part_stock_version must match the row's current version.
    if expected != stock["version"]:
        raise_err(ERR_STALE_VERSION, "expected_part_stock_version does not match")
    # Capacity/quota last: on-hand never below live reserved quantity.
    effective_on_hand = stock["quantity_on_hand"] if new_on_hand is None else new_on_hand
    if effective_on_hand < services.reserved_qty(stock["id"]):
        raise_err(ERR_STOCK_BELOW_RESERVED, "quantity_on_hand would fall below reserved")
    changed = False
    if new_on_hand is not None and new_on_hand != stock["quantity_on_hand"]:
        stock["quantity_on_hand"] = new_on_hand
        changed = True
    if new_cost is not None and new_cost != stock["unit_cost_cents"]:
        stock["unit_cost_cents"] = new_cost
        changed = True
    if changed:
        db.touch(stock)
    return success(ser.stock(stock), 200)


# ---------------------------------------------------------- part reservations ---

@bp.post("/api/part-reservations")
@require_roles("Coordinator", "Fixer")
def create_reservation():
    b = body()
    # Existence (priority 3): body FKs in declared order.
    stock_id = as_str(req(b, "part_stock_id"), "part_stock_id")
    stock = get_stock_or_404(stock_id)
    item_id = as_str(req(b, "repair_item_id"), "repair_item_id")
    item = db.items.get(item_id)
    if item is None:
        raise_err(ERR_ITEM_NOT_FOUND, "RepairItem %s does not exist" % item_id)
    quantity = as_int(req(b, "quantity"), "quantity", lo=1)
    # The item must be in a non-terminal repair flow: ASSIGNED or IN_REPAIR.
    if item["status"] not in ("ASSIGNED", "IN_REPAIR"):
        raise_err(ERR_INVALID_ITEM_STATE, "Item is not in ASSIGNED or IN_REPAIR")
    # Capacity/quota last.
    available = stock["quantity_on_hand"] - services.reserved_qty(stock["id"])
    if quantity > available:
        raise_err(ERR_INSUFFICIENT_STOCK, "Requested quantity exceeds availability")
    event = db.events[item["event_id"]]
    rec = db.stamp_new(
        {
            "part_stock_id": stock_id,
            "repair_item_id": item_id,
            "quantity": quantity,
            "unit_cost_cents": stock["unit_cost_cents"],
            "cost_cents": quantity * stock["unit_cost_cents"],
            "status": "RESERVED",
            "expires_at": event["ends_at"],
        }
    )
    db.reservations[rec["id"]] = rec
    return success(ser.reservation(rec), 201)


@bp.get("/api/part-reservations")
@require_roles(*ALL_ROLES)
def list_reservations():
    return list_response(
        db.reservations.values(),
        ser.reservation,
        [
            ("part_stock_id", "part_stock_id"),
            ("repair_item_id", "repair_item_id"),
            ("status", "status"),
        ],
    )


@bp.get("/api/part-reservations/<reservation_id>")
@require_roles(*ALL_ROLES)
def get_reservation(reservation_id):
    return success(ser.reservation(get_reservation_or_404(reservation_id)), 200)


@bp.post("/api/part-reservations/<reservation_id>/commit")
@require_roles("Coordinator", "Fixer")
def commit_reservation(reservation_id):
    reservation = get_reservation_or_404(reservation_id)
    if reservation["status"] != "RESERVED":
        raise_err(ERR_INVALID_RESERVATION_STATE, "Only a RESERVED reservation can be committed")
    # A commit past expiry fails WITHOUT flipping the reservation's status.
    if db.clock.current > db.parse_dt(reservation["expires_at"]):
        raise_err(ERR_RESERVATION_EXPIRED, "Reservation has expired")
    # Safety gate: no open HIGH/CRITICAL incident on the item.
    for inc in db.incidents.values():
        if (
            inc["item_id"] == reservation["repair_item_id"]
            and inc["status"] == "REPORTED"
            and inc["severity"] in ("HIGH", "CRITICAL")
        ):
            raise_err(ERR_SAFETY_HOLD, "An open HIGH/CRITICAL incident exists for this item")
    stock = db.stocks[reservation["part_stock_id"]]
    stock["quantity_on_hand"] -= reservation["quantity"]
    db.touch(stock)
    reservation["status"] = "COMMITTED"
    db.touch(reservation)
    return success(ser.reservation(reservation), 200)


@bp.post("/api/part-reservations/<reservation_id>/release")
@require_roles("Coordinator", "Fixer")
def release_reservation(reservation_id):
    reservation = get_reservation_or_404(reservation_id)
    if reservation["status"] != "RESERVED":
        raise_err(ERR_INVALID_RESERVATION_STATE, "Only a RESERVED reservation can be released")
    services.release_reservation(reservation)
    return success(ser.reservation(reservation), 200)
