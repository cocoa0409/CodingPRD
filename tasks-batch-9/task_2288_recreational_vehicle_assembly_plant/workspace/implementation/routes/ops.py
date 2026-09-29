"""Ops: the logical clock, the daily-close checkpoint and the test-driving injection."""
import uuid
from decimal import Decimal

import db
import response
import validation as V
from db import store
from errors import bad_request
from flask import Blueprint
from middleware import authorize
from routes.common import insert, must_find, object_out
from services import calc, cascade, derive

bp = Blueprint("ops", __name__)


# ---------------------------------------------------------------------------
# the logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
@authorize("PlantAdmin")
def set_clock():
    body = V.body_dict()
    current = V.field_datetime(body, "current_utc", required=True)
    previous = store.clock
    if current <= previous:
        raise bad_request("Field 'current_utc' must be strictly after the current clock.")
    store.clock = current
    return response.object_response(
        {
            "current_utc": db.iso_instant(current),
            "previous_utc": db.iso_instant(previous),
        }
    )


# ---------------------------------------------------------------------------
# the daily-close checkpoint
# ---------------------------------------------------------------------------
@bp.post("/daily-close")
@authorize("PlantAdmin")
def daily_close():
    V.body_dict()
    now = db.now()

    released_slot_count = 0
    released_order_ids = []
    expired = [
        slot
        for slot in store.production_slots.values()
        if slot["status"] == "RESERVED" and slot["expires_at"] <= now
    ]
    for slot in db.ordered(expired):
        order = cascade.expiry_release_cascade(slot)
        released_slot_count += 1
        if order is not None:
            released_order_ids.append(order["id"])

    curtailed_order_ids = []
    for order in db.ordered(list(store.unit_orders.values())):
        if order["financing_status"] != "FLOOR_PLAN_FUNDED":
            continue
        if derive.order_curtailment_due(order) <= 0:
            continue
        order["financing_status"] = "CURTAILED"
        db.touch(order)
        curtailed_order_ids.append(order["id"])

    # the trust score is recomputed on every daily close (PRD §3.9)
    for supplier in store.suppliers.values():
        derive.rescore_supplier(supplier)

    return response.object_response(
        {
            "released_slot_count": released_slot_count,
            "released_order_ids": released_order_ids,
            "curtailed_order_count": len(curtailed_order_ids),
            "curtailed_order_ids": curtailed_order_ids,
            "evaluated_at": db.iso_instant(now),
        }
    )


# ---------------------------------------------------------------------------
# test-driving injection
# ---------------------------------------------------------------------------
@bp.post("/_inject/delivered-unit")
@authorize("PlantAdmin")
def inject_delivered_unit():
    body = V.body_dict()
    dealer_id = V.field_string(body, "dealer_id", required=True, min_len=1)
    floor_plan_id = V.field_string(body, "floor_plan_id", required=True, min_len=1)
    shipped_at = V.field_datetime(body, "shipped_at")
    must_find("dealers", dealer_id)
    floor_plan = must_find("floor_plans", floor_plan_id)

    if shipped_at is None:
        shipped_at = db.now()
    totals = calc.configuration_totals(floor_plan, [])

    order = db.new_row(
        {
            "dealer_id": dealer_id,
            "floor_plan_id": floor_plan_id,
            "order_type": "SOLD",
            "customer_reference": None,
            "selected_option_ids": [],
            "requested_delivery_date": shipped_at,
            "status": "SHIPPED",
            "financing_status": "NOT_FINANCED",
            "option_price_total_cents": totals["option_price_total_cents"],
            "config_weight_lbs": totals["config_weight_lbs"],
            "payload_remaining_lbs": totals["payload_remaining_lbs"],
            "total_amp_draw": totals["total_amp_draw"],
            "total_water_demand_gal": totals["total_water_demand_gal"],
            "required_station_hours": totals["required_station_hours"],
            "provisional_invoice_cents": 0,
            "final_invoice_cents": None,
            "locked_floor_plan_version": None,
            "locked_option_versions": [],
            "financed_principal_cents": 0,
            "curtailment_paid_cents": 0,
            "funded_at": None,
            "shipped_at": shipped_at,
            "ship_hold_reason": "NONE",
        }
    )
    insert("unit_orders", order)

    chassis = db.new_row(
        {
            "supplier_id": None,
            "chassis_serial": "SYN-" + uuid.uuid4().hex[:12].upper(),
            "chassis_class": floor_plan["chassis_class"],
            "gvwr_lbs": int(floor_plan["gvwr_lbs"]),
            "wheelbase_in": int(floor_plan["required_wheelbase_in"]),
            "received_at": db.now(),
            "matched_unit_order_id": order["id"],
            "status": "INSTALLED",
        }
    )
    insert("chassis_receipts", chassis)

    store.build_counter += 1
    sequence = store.build_counter
    build = db.new_row(
        {
            "unit_order_id": order["id"],
            "chassis_receipt_id": chassis["id"],
            "vin": "{}-{:06d}".format(floor_plan["model_code"], sequence),
            "build_sequence": sequence,
            "current_station": "SHIPPED",
            "actual_station_hours": Decimal("0.00"),
            "rework_count": 0,
            "defect_points_total": 0,
            "water_test_passed": True,
            "pdi_passed": True,
            "recall_hold": False,
        }
    )
    insert("unit_builds", build)
    return object_out("unit_builds", build, 201)
