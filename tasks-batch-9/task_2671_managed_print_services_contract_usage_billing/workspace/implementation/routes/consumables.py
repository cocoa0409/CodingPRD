"""Consumable (toner) replenishment endpoints (PRD 3.5)."""
from flask import Blueprint

import cascade
import derive
import serialize
import validation as v
from auth import require
from envelope import created, ok, ok_list
from errors import fail
from resolve import get_device, get_order
from store import db, touch

bp = Blueprint("consumables", __name__)

PART_TYPES = ("TONER_BLACK", "TONER_COLOR")
CANCEL_REASONS = ("HOARDING_CONTROL", "WRONG_PART", "DEVICE_REMOVED", "READ_VOIDED")
MANUAL_SUPPLY_STATES = ("SUPPLY_LOW", "SUPPLY_BLOCKED")


@bp.post("/consumable-orders")
def create_consumable_order():
    require("FleetOpsController")
    body = v.body()
    device_id = v.id_field(body, "device_id")
    part_type = v.enum_field(body, "part_type", PART_TYPES)
    unit_price = v.int_field(body, "unit_price_cents", minimum=1)
    expected = v.int_field(body, "expected_device_version")
    quantity = v.int_field(body, "quantity", required=False, minimum=1, maximum=3, default=1)
    device = get_device(device_id)

    if expected != device["version"]:
        fail("ERR_STALE_DEVICE_VERSION",
             "expected_device_version %d does not match the device's current version %d."
             % (expected, device["version"]))
    if device["supply_state"] not in MANUAL_SUPPLY_STATES:
        fail("ERR_DEVICE_INVALID_STATE",
             "A device in %s cannot take a manual replenishment order." % device["supply_state"])
    contract = derive.device_contract(device)
    if contract is None or contract["status"] != "ACTIVE":
        fail("ERR_CONTRACT_NOT_ACTIVE", "The governing contract is not ACTIVE.")

    site = derive.device_site(device)
    existing = derive.open_order_for_device(device["id"])
    superseded_units = existing["quantity"] if existing is not None else 0
    if site is not None:
        projected = derive.open_toner_units(site["id"]) - superseded_units + quantity
        if projected > site["toner_unit_cap"]:
            fail("ERR_TONER_CAP_EXCEEDED",
                 "The site's toner_unit_cap of %d would be exceeded." % site["toner_unit_cap"])

    if existing is not None:
        existing["status"] = "CANCELLED"
        existing["cancel_reason"] = "HOARDING_CONTROL"
        touch(existing)
    device["supply_state"] = "SUPPLY_ORDERED"
    order = cascade.create_order(device, part_type, quantity, unit_price, "MANUAL")
    touch(device)
    return created(serialize.order(order))


@bp.get("/consumable-orders/<order_id>")
def read_order(order_id):
    require("FleetOpsController", "FieldTechnician", "BillingAnalyst", "AccountManager")
    order = get_order(order_id)
    return ok(serialize.order(order))


@bp.get("/consumable-orders")
def list_orders():
    require("FleetOpsController", "FieldTechnician", "BillingAnalyst", "AccountManager")
    rows = db.sorted_rows("orders")
    for field in ("device_id", "status", "trigger_source"):
        value = v.query_filter(field)
        if value is not None:
            rows = [o for o in rows if o[field] == value]
    data, meta = v.paginate(rows, serialize.order)
    return ok_list(data, meta)


@bp.post("/consumable-orders/<order_id>/deliver")
def deliver_order(order_id):
    require("FieldTechnician")
    order = get_order(order_id)
    v.body()
    if order["status"] != "ORDERED":
        fail("ERR_ORDER_INVALID_STATE",
             "An order in %s cannot be delivered." % order["status"])
    device = db.devices.get(order["device_id"])
    if device is not None and device["lifecycle_state"] == "REMOVED":
        fail("ERR_DEVICE_INVALID_STATE", "A REMOVED device cannot take a cartridge.")
    cascade.deliver_order(order, device)
    return ok(serialize.order(order))


@bp.post("/consumable-orders/<order_id>/cancel")
def cancel_order(order_id):
    require("FleetOpsController")
    order = get_order(order_id)
    body = v.body()
    cancel_reason = v.enum_field(body, "cancel_reason", CANCEL_REASONS)
    if order["status"] != "ORDERED":
        fail("ERR_ORDER_INVALID_STATE",
             "An order in %s cannot be cancelled." % order["status"])
    device = db.devices.get(order["device_id"])
    cascade.cancel_order(order, device, cancel_reason)
    return ok(serialize.order(order))
