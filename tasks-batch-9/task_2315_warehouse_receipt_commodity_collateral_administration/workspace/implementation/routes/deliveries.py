"""Delivery orders: booking, cancellation, loadout and settlement (§3.8)."""

from flask import Blueprint

import calc
import model
from core import (authenticate, body, dec, fail, invalid, new_row, now, now_iso,
                  opt_str, req_datetime, req_int, req_number, req_str,
                  respond_object, rhu, store, touch)
from listing import list_response

bp = Blueprint("deliveries", __name__)

READ_ROLES = ("StateRegulator", "WarehouseOperator", "Depositor", "Lender")
LIVE_STATES = ("REQUESTED", "LOADED")


@bp.post("/delivery-orders")
def create_order():
    caller = authenticate(("Depositor", "Lender"))
    data = body()
    receipt_id = req_str(data, "receipt_id")
    requested = req_int(data, "requested_bushels", minimum=1)
    start = req_datetime(data, "appointment_start_at")
    end = req_datetime(data, "appointment_end_at")
    if end <= start:
        invalid("appointment_end_at", "must be strictly after appointment_start_at")

    receipt = model.get_receipt(receipt_id)
    if caller.user_id != receipt["holder_party_id"]:
        model.not_owner()

    if receipt["receipt_state"] != "ISSUED":
        fail("ERR_INVALID_STATE", 409)

    warehouse = store.warehouses[receipt["warehouse_id"]]
    model.gate_licensed(warehouse)
    model.gate_solvent(warehouse)
    bin_row = store.bins[receipt["bin_id"]]
    model.gate_bin_condition(bin_row)

    taken = set()
    for other in store.orders.values():
        if other["delivery_state"] not in LIVE_STATES:
            continue
        other_receipt = store.receipts.get(other["receipt_id"])
        if (other_receipt is None
                or other_receipt["warehouse_id"] != warehouse["id"]):
            continue
        if start < other["_appointment_end_dt"] and other["_appointment_start_dt"] < end:
            taken.add(other["lane_index"])
    lane_index = None
    for candidate in range(warehouse["loadout_lane_count"]):
        if candidate not in taken:
            lane_index = candidate
            break
    if lane_index is None:
        fail("ERR_LOADOUT_CAPACITY_EXCEEDED", 409)

    if requested > receipt["quantity_bushels"]:
        fail("ERR_DELIVERY_EXCEEDS_RECEIPT", 422)

    row = new_row()
    row.update({
        "receipt_id": receipt_id,
        "requester_party_id": caller.user_id,
        "requested_bushels": requested,
        "appointment_start_at": data["appointment_start_at"],
        "appointment_end_at": data["appointment_end_at"],
        "_appointment_start_dt": start,
        "_appointment_end_dt": end,
        "lane_index": lane_index,
        "delivered_bushels": None,
        "delivered_test_weight_lbs": None,
        "delivered_moisture_pct": None,
        "delivered_damage_pct": None,
        "delivered_foreign_material_pct": None,
        "delivered_grade": None,
        "grade_delta_bps": None,
        "settlement_price_cents_per_bushel": None,
        "quality_adjustment_cents": None,
        "storage_charge_cents": None,
        "loadout_charge_cents": None,
        "net_settlement_cents": None,
        "delivery_state": "REQUESTED",
        "loaded_at": None,
        "settled_at": None,
        "cancelled_at": None,
        "cancellation_reason": None,
    })
    store.orders[row["id"]] = row
    return respond_object(model.order_out(row), 201)


@bp.get("/delivery-orders")
def list_orders():
    authenticate(READ_ROLES)
    return list_response(list(store.orders.values()),
                         ("receipt_id", "requester_party_id", "delivery_state"),
                         model.order_out)


def _require_order_access(caller, order):
    receipt = model.order_receipt(order)
    if caller.role == "WarehouseOperator":
        if caller.user_id != receipt["warehouse_id"]:
            model.not_owner()
    elif caller.role in ("Depositor", "Lender"):
        allowed = {order["requester_party_id"], receipt["holder_party_id"],
                   receipt["registry_control_party_id"]}
        if caller.user_id not in allowed:
            model.not_owner()
    return receipt


@bp.get("/delivery-orders/<order_id>")
def read_order(order_id):
    caller = authenticate(READ_ROLES)
    order = model.get_order(order_id)
    _require_order_access(caller, order)
    return respond_object(model.order_out(order))


@bp.post("/delivery-orders/<order_id>/cancel")
def cancel_order(order_id):
    caller = authenticate(("Depositor", "Lender"))
    order = model.get_order(order_id)
    if caller.user_id != order["requester_party_id"]:
        model.not_owner()
    data = body()
    reason = opt_str(data, "cancellation_reason")

    if order["delivery_state"] != "REQUESTED":
        fail("ERR_INVALID_STATE", 409)

    order["delivery_state"] = "CANCELLED"
    order["cancelled_at"] = now_iso()
    order["cancellation_reason"] = reason
    touch(order)
    return respond_object(model.order_out(order))


@bp.post("/delivery-orders/<order_id>/load")
def load_order(order_id):
    caller = authenticate(("WarehouseOperator",))
    order = model.get_order(order_id)
    receipt = model.order_receipt(order)
    if caller.user_id != receipt["warehouse_id"]:
        model.not_owner()
    data = body()
    delivered = req_int(data, "delivered_bushels", minimum=1)
    test_weight = req_number(data, "delivered_test_weight_lbs", minimum=0)
    moisture = req_number(data, "delivered_moisture_pct", minimum=0)
    damage = req_number(data, "delivered_damage_pct", minimum=0)
    foreign = req_number(data, "delivered_foreign_material_pct", minimum=0)

    if order["delivery_state"] != "REQUESTED":
        fail("ERR_INVALID_STATE", 409)

    warehouse = store.warehouses[receipt["warehouse_id"]]
    model.gate_licensed(warehouse)
    model.gate_solvent(warehouse)
    bin_row = store.bins[receipt["bin_id"]]
    model.gate_bin_condition(bin_row)

    if delivered > order["requested_bushels"]:
        fail("ERR_DELIVERY_EXCEEDS_RECEIPT", 422)

    agreement = model.receipt_agreement(receipt)
    grade = calc.assign_grade(test_weight, damage, foreign)
    order.update({
        "delivered_bushels": delivered,
        "delivered_test_weight_lbs": test_weight,
        "delivered_moisture_pct": moisture,
        "delivered_damage_pct": damage,
        "delivered_foreign_material_pct": foreign,
        "delivered_grade": grade,
        "grade_delta_bps": calc.grade_delta_bps(grade, receipt["grade"]),
        "storage_charge_cents": calc.storage_charge_accrual(
            "FINAL", receipt["quantity_bushels"],
            agreement["storage_rate_millicents_per_bushel_day"],
            agreement["free_storage_days"], receipt["_issued_at_dt"],
            now().date()),
        "loadout_charge_cents": calc.loadout_charge(
            delivered, agreement["loadout_charge_cents_per_bushel"]),
        "delivery_state": "LOADED",
        "loaded_at": now_iso(),
    })
    touch(order)
    return respond_object(model.order_out(order))


@bp.post("/delivery-orders/<order_id>/settle")
def settle_order(order_id):
    caller = authenticate(("WarehouseOperator",))
    order = model.get_order(order_id)
    receipt = model.order_receipt(order)
    if caller.user_id != receipt["warehouse_id"]:
        model.not_owner()
    data = body()
    price = req_int(data, "settlement_price_cents_per_bushel", minimum=1)

    if order["delivery_state"] != "LOADED":
        fail("ERR_INVALID_STATE", 409)
    if receipt["encumbrance_state"] == "PLEDGED":
        fail("ERR_RECEIPT_ENCUMBERED", 409)

    delivered = order["delivered_bushels"]
    quality = calc.quality_adjustment(delivered, price, order["grade_delta_bps"])
    net = (quality - order["storage_charge_cents"]
           - order["loadout_charge_cents"])
    full = delivered == receipt["quantity_bushels"]

    order.update({
        "settlement_price_cents_per_bushel": price,
        "quality_adjustment_cents": quality,
        "net_settlement_cents": net,
        "settled_at": now_iso(),
        "delivery_state": "SETTLED_FULL" if full else "SETTLED_PARTIAL",
    })
    touch(order)

    bin_row = store.bins.get(receipt["bin_id"])
    if bin_row is not None:
        bin_row["stored_bushels"] = bin_row["stored_bushels"] - delivered
        touch(bin_row)

    if full:
        receipt["quantity_bushels"] = 0
        receipt["receipt_state"] = "CANCELLED"
    else:
        receipt["quantity_bushels"] = receipt["quantity_bushels"] - delivered
    touch(receipt)

    return respond_object(model.order_out(order))
