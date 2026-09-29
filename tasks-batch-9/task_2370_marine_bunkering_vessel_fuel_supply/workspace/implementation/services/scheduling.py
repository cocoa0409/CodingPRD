"""Shared slot admissibility and order creation (PRD 3.4)."""

from datetime import timedelta

import db
from db import store, touch
from errors import ApiError
from services import calc, cascade


def check_slot_in_window(nomination, slot_start, slot_end):
    if slot_start < nomination["window_start"] or slot_end > nomination["window_end"]:
        raise ApiError("ERR_SLOT_OUTSIDE_WINDOW")


def check_notice_period(port, slot_start):
    earliest = db.now() + timedelta(hours=port["notice_lead_hours"])
    if slot_start < earliest:
        raise ApiError("ERR_NOTICE_PERIOD_MISSED")


def supersede_orders(nomination):
    """Any SCHEDULED or CLEARED order on the nomination is cancelled."""
    for order in db.sorted_rows(store.delivery_orders):
        if order["nomination_id"] != nomination["id"]:
            continue
        if order["logistics_status"] not in ("SCHEDULED", "CLEARED"):
            continue
        cascade.cancel_order(order, cascade_nomination=False)


def create_order(nomination, asset, planned_quantity_mt, slot_start, slot_end):
    order = db.new_record()
    order.update(
        {
            "nomination_id": nomination["id"],
            "asset_id": asset["id"],
            "planned_quantity_mt": planned_quantity_mt,
            "slot_start": slot_start,
            "slot_end": slot_end,
            "logistics_status": "SCHEDULED",
            "measurement_status": "NOT_STARTED",
            "barge_sounding_mt": None,
            "vessel_sounding_mt": None,
            "meter_mt": None,
            "surveyed_mt": None,
            "agreed_quantity_mt": None,
            "measurement_basis": None,
            "shortfall_mt": None,
            "port_clearance_ref": None,
            "cleared_at": None,
        }
    )
    store.delivery_orders[order["id"]] = order
    calc.recompute_committed_quantity(asset)
    touch(asset)
    nomination["fulfillment_status"] = "SCHEDULED"
    touch(nomination)
    return order
