"""Sale endpoints (PRD 3.6): record (FIFO), list, get, void."""
from flask import Blueprint, request

from common import get_json_body, get_or_404, list_response, require_enum, require_int, require_str
from db import db, stamp_create, touch
from errors import ApiError
from middleware import require_roles
from response import object_response
from services import serialize
from services.inventory import (available_lots, recompute_slot_on_hand,
                                rederive_machine_cash, rederive_machine_stock)
from services.money import round_half_up

bp = Blueprint("sales", __name__)

ALL_ROLES = ("FieldOps", "RouteDriver", "HostManager", "FinanceClerk")


def _sort_key(l):
    """FIFO order: expiration_date ASC with NULLS LAST, tie-break created_at ASC
    (never by id). Internal _seq disambiguates identical created_at timestamps."""
    exp = l.get("_expiration_dt")
    if exp is None:
        return (1, 0.0, l["created_at"], l["_seq"])
    return (0, exp.timestamp(), l["created_at"], l["_seq"])


def _fifo_order(lots):
    return sorted(lots, key=_sort_key)


@bp.route("/operations/sales", methods=["POST"])
@require_roles("FieldOps", "HostManager")
def create_sale():
    body = get_json_body()
    machine_id = require_str(body, "machine_id")
    slot_id = require_str(body, "slot_id")
    quantity = require_int(body, "quantity")
    payment_method = require_enum(body, "payment_method", {"CASHLESS", "CASH"})
    settlement_status = require_enum(body, "settlement_status", {"SETTLED", "VOID"},
                                     allow_missing=True, default="SETTLED")
    if quantity <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "quantity must be > 0")

    # FK existence (priority 4)
    machine = db.machines.get(machine_id)
    if machine is None:
        raise ApiError("ERR_MACHINE_NOT_FOUND", "Machine not found")
    slot = db.slots.get(slot_id)
    if slot is None:
        raise ApiError("ERR_SLOT_NOT_FOUND", "Slot not found")

    # business_safety (priority 7): machine must not be FROZEN
    if machine["service_status"] == "FROZEN":
        raise ApiError("ERR_MACHINE_FROZEN", "Machine is frozen")

    # business_referential (priority 8): slot belongs to machine and is ACTIVE
    if slot["machine_id"] != machine_id or slot["status"] != "ACTIVE":
        raise ApiError("ERR_SLOT_NOT_ON_MACHINE",
                       "Slot does not belong to this machine or is not active")

    # Build the sale record.
    sale = {
        "machine_id": machine_id,
        "slot_id": slot_id,
        "lot_consumption_json": [],
        "quantity": quantity,
        "unit_price_cents": None,
        "gross_cents": None,
        "provisional_cogs_cents": None,
        "payment_method": payment_method,
        "settlement_status": settlement_status,
    }

    if settlement_status == "VOID":
        # A sale created directly as VOID has no side effects (it never settled).
        sale["unit_price_cents"] = slot["price_cents"]
        sale["gross_cents"] = quantity * slot["price_cents"]
        sale["provisional_cogs_cents"] = 0
        stamp_create(sale, common_fields=False)
        db.sales[sale["id"]] = sale
        return object_response(serialize.sale(sale), 201)

    # SETTLED path.
    unit_price = slot["price_cents"]
    gross = quantity * unit_price

    avail = available_lots(slot_id)
    on_hand = sum(l["remaining_units"] for l in avail)

    # provisional COGS: slot weighted-average over AVAILABLE lots BEFORE draw-down
    if on_hand > 0:
        weighted = sum(l["remaining_units"] * l["unit_cost_cents"] for l in avail)
        avg_cost = round_half_up(weighted / on_hand)
    else:
        avg_cost = 0
    provisional_cogs = avg_cost * quantity

    # business_fiscal (priority 15): quantity must not exceed on_hand
    if quantity > on_hand:
        raise ApiError("ERR_INSUFFICIENT_STOCK", "Quantity exceeds slot on_hand")

    # FIFO draw
    ordered = _fifo_order(avail)
    remaining = quantity
    consumption = []
    for lot in ordered:
        if remaining == 0:
            break
        take = min(remaining, lot["remaining_units"])
        if take <= 0:
            continue
        lot["remaining_units"] -= take
        if lot["remaining_units"] == 0:
            lot["status"] = "DEPLETED"
        touch(lot)
        consumption.append({"lot_id": lot["id"], "units": take})
        remaining -= take

    sale["unit_price_cents"] = unit_price
    sale["gross_cents"] = gross
    sale["provisional_cogs_cents"] = provisional_cogs
    sale["lot_consumption_json"] = consumption
    stamp_create(sale, common_fields=False)
    db.sales[sale["id"]] = sale

    # recompute slot on_hand; re-derive machine stock_status
    recompute_slot_on_hand(slot)
    rederive_machine_stock(machine)

    # cash side effect
    if payment_method == "CASH":
        machine["cash_on_hand_cents"] += gross
        rederive_machine_cash(machine)

    return object_response(serialize.sale(sale), 201)


@bp.route("/operations/sales", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_sales():
    rows = list(db.sales.values())
    machine_id = request.args.get("machine_id")
    slot_id = request.args.get("slot_id")
    if machine_id is not None:
        rows = [s for s in rows if s["machine_id"] == machine_id]
    if slot_id is not None:
        rows = [s for s in rows if s["slot_id"] == slot_id]
    return list_response(rows, serialize.sale)


@bp.route("/operations/sales/<sale_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_sale(sale_id):
    obj = get_or_404("sales", sale_id)
    return object_response(serialize.sale(obj))


@bp.route("/operations/sales/<sale_id>/void", methods=["POST"])
@require_roles("FieldOps")
def void_sale(sale_id):
    sale = get_or_404("sales", sale_id)
    if sale["settlement_status"] != "SETTLED":
        raise ApiError("ERR_SALE_NOT_SETTLED", "Sale is not SETTLED")

    machine = db.machines.get(sale["machine_id"])
    slot = db.slots.get(sale["slot_id"])

    # compensating reversal: restore remaining_units per lot_consumption_json
    for entry in sale["lot_consumption_json"]:
        lot = db.lots.get(entry["lot_id"])
        if lot is None:
            continue
        was_depleted = lot["status"] == "DEPLETED"
        lot["remaining_units"] += entry["units"]
        # revert DEPLETED lots this sale depleted back to AVAILABLE
        if was_depleted and lot["remaining_units"] > 0:
            lot["status"] = "AVAILABLE"
        touch(lot)

    sale["settlement_status"] = "VOID"
    # Sale has no version/updated_at — voiding does not mutate versioning fields.

    if slot is not None:
        recompute_slot_on_hand(slot)
    if machine is not None:
        rederive_machine_stock(machine)
        if sale["payment_method"] == "CASH":
            machine["cash_on_hand_cents"] -= sale["gross_cents"]
            rederive_machine_cash(machine)

    return object_response(serialize.sale(sale))
