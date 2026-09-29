"""Shared reservation machinery: delivery creation, zone policy, timing, capacity."""

from datetime import timedelta

from constants import COLD_CLASSES, CONTROLLED_CLASSES, DISPATCH_LEAD_MINUTES
from db import db, new_row
from errors import api_error
from services import derive
from services import orders as order_service

RELEASED_CUSTODY = {"CANCELLED", "RETURNED"}


def zone_of(window):
    return db.delivery_zones.get(window["zone_id"])


def patient_of(order):
    return db.patients.get(order["patient_id"])


def new_delivery(order, window, reship_of_delivery_id=None):
    """Snapshot the three handling values off the order; never re-derived later."""
    row = new_row()
    row["order_id"] = order["id"]
    row["window_id"] = window["id"]
    row["courier_id"] = None
    row["reship_of_delivery_id"] = reship_of_delivery_id
    row["custody_status"] = "QUEUED"
    row["settlement_status"] = "PROVISIONAL"
    row["handling_class"] = order_service.handling_class(order)
    row["signature_required"] = order["signature_required"]
    row["required_id_verification"] = order["required_id_verification"]
    row["excluded_courier_ids"] = []
    row["cold_chain_seal_id"] = None
    row["picked_up_at"] = None
    row["delivered_at"] = None
    row["return_due_at"] = None
    row["fee_subtotal_cents"] = 0
    db.deliveries[row["id"]] = row
    return row


# ---- ladder helpers ------------------------------------------------------
def assert_window_not_blocked(window, reservation=True):
    """Rung 18: status flag only; the clock comparison lives at rung 34."""
    if window["status"] == "CLOSED":
        raise api_error("ERR_WINDOW_CLOSED", "The target window is CLOSED.")
    if reservation and window["status"] == "FULL":
        raise api_error("ERR_WINDOW_CLOSED", "The target window is FULL.")


def assert_zone_policy(zone, handling_class):
    """Rungs 24 and 25, in ladder order."""
    if handling_class in CONTROLLED_CLASSES and not zone["controlled_delivery_allowed"]:
        raise api_error("ERR_CONTROLLED_ZONE_PROHIBITED",
                        "Controlled substances may not be routed into this zone.")
    if handling_class in COLD_CLASSES and not zone["cold_chain_supported"]:
        raise api_error("ERR_COLD_CHAIN_UNSUPPORTED_ZONE",
                        "This zone does not support cold-chain delivery.")


def assert_patient_zone(order, window):
    """Rung 30."""
    patient = patient_of(order)
    zone = None
    for candidate in db.delivery_zones.values():
        if candidate["zone_code"] == patient["zone_code"]:
            zone = candidate
            break
    if zone is None:
        raise api_error("ERR_ZONE_NOT_SERVICED",
                        "The recipient's zone_code names no serviced zone.")
    if window["zone_id"] != zone["id"]:
        raise api_error("ERR_ZONE_MISMATCH",
                        "The target window belongs to a different zone.")
    return zone


def assert_mode_match(current_window, new_window):
    """Rung 31."""
    if new_window["courier_mode"] != current_window["courier_mode"]:
        raise api_error("ERR_WINDOW_MODE_MISMATCH",
                        "On-demand and scheduled capacity pools are not interchangeable.")


def assert_no_duplicate_active(order, exclude_delivery_id=None):
    """Rung 32."""
    for delivery in db.deliveries.values():
        if delivery["order_id"] != order["id"]:
            continue
        if exclude_delivery_id and delivery["id"] == exclude_delivery_id:
            continue
        if delivery["custody_status"] not in RELEASED_CUSTODY:
            raise api_error("ERR_DUPLICATE_ACTIVE_DELIVERY",
                            "The order already has a live delivery.")


def assert_window_timing(window, new_reservation=False):
    """Rung 34."""
    if db.clock >= window["window_end"]:
        raise api_error("ERR_WINDOW_ELAPSED", "The target window has elapsed.")
    if new_reservation and window["courier_mode"] == "SCHEDULED":
        cutoff = window["window_start"] - timedelta(minutes=DISPATCH_LEAD_MINUTES)
        if db.clock > cutoff:
            raise api_error("ERR_WINDOW_ELAPSED",
                            "A scheduled window must be reserved at least two hours "
                            "before it starts.")


def assert_capacity(window):
    """Rung 38."""
    if derive.available_slots(window) < 1:
        raise api_error("ERR_WINDOW_FULL", "The target window has no available slots.")
