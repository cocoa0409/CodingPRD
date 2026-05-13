"""RecurringOrder lifecycle."""
from datetime import timedelta

from db import store, iso_to_dt
from errors import (
    ERR_VALIDATION_ERROR, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_AREA_NOT_SERVICED, ERR_ITEM_INACTIVE, ERR_LEAD_TIME_TOO_SHORT,
    raise_error,
)
from services.utils import stamp_create, stamp_update


def create_recurring_order(body: dict, caller_role: str, caller_id: str) -> dict:
    required = ["customer_id", "service_item_id", "cadence_days", "first_start_at", "duration_hours"]
    for f in required:
        if f not in body or body[f] is None:
            raise_error(ERR_VALIDATION_ERROR, f"Missing required field: {f}")
    if body["customer_id"] not in store.customers:
        raise_error(ERR_NOT_FOUND, "Customer not found")
    if body["service_item_id"] not in store.service_items:
        raise_error(ERR_NOT_FOUND, "Service item not found")
    cadence = body["cadence_days"]
    if cadence not in {1, 7, 14, 30}:
        raise_error(ERR_VALIDATION_ERROR, "cadence_days must be in {1,7,14,30}")
    try:
        dh = float(body["duration_hours"])
    except (TypeError, ValueError):
        raise_error(ERR_VALIDATION_ERROR, "duration_hours must be a number")
    if (dh * 2) != int(dh * 2):
        raise_error(ERR_VALIDATION_ERROR, "duration_hours must be a multiple of 0.5")
    if caller_role == "Customer" and caller_id != body["customer_id"]:
        raise_error(ERR_NOT_FOUND, "Customer not found")
    customer = store.customers[body["customer_id"]]
    item = store.service_items[body["service_item_id"]]
    if customer["area_code"] not in item["service_areas"]:
        raise_error(ERR_AREA_NOT_SERVICED, "Customer area not in service areas")
    if not item["active"]:
        raise_error(ERR_ITEM_INACTIVE, "Service item is inactive")
    sched_dt = iso_to_dt(body["first_start_at"])
    if sched_dt is None:
        raise_error(ERR_VALIDATION_ERROR, "Invalid first_start_at")

    record = {
        "customer_id": body["customer_id"],
        "service_item_id": body["service_item_id"],
        "cadence_days": int(cadence),
        "first_start_at": body["first_start_at"],
        "duration_hours": dh,
        "occurrences_generated": 0,
        "status": "ACTIVE",
    }
    stamp_create(record)
    store.recurring_orders[record["id"]] = record

    # Materialize first Order child
    first_order = {
        "customer_id": body["customer_id"],
        "service_item_id": body["service_item_id"],
        "mode": "RECURRING",
        "recurring_order_id": record["id"],
        "scheduled_start_at": body["first_start_at"],
        "duration_hours": dh,
        "gross_price_cents": 0,
        "status": "DRAFT",
        "assigned_personnel_id": None,
        "dispatch_round": 0,
        "dispatch_deadline_at": None,
        "completed_at": None,
        "accepted_at": None,
        "refunded_at": None,
        "rated": False,
    }
    stamp_create(first_order)
    store.orders[first_order["id"]] = first_order
    record["occurrences_generated"] = 1
    stamp_update(record)
    return record


def pause_recurring(ro_id: str, caller_role: str, caller_id: str) -> dict:
    if ro_id not in store.recurring_orders:
        raise_error(ERR_NOT_FOUND, "Recurring order not found")
    ro = store.recurring_orders[ro_id]
    if caller_role == "Customer" and caller_id != ro["customer_id"]:
        raise_error(ERR_NOT_FOUND, "Recurring order not found")
    if ro["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "Recurring order must be ACTIVE to pause")
    ro["status"] = "PAUSED"
    stamp_update(ro)
    return ro


def resume_recurring(ro_id: str, caller_role: str, caller_id: str) -> dict:
    if ro_id not in store.recurring_orders:
        raise_error(ERR_NOT_FOUND, "Recurring order not found")
    ro = store.recurring_orders[ro_id]
    if caller_role == "Customer" and caller_id != ro["customer_id"]:
        raise_error(ERR_NOT_FOUND, "Recurring order not found")
    if ro["status"] != "PAUSED":
        raise_error(ERR_INVALID_STATE, "Recurring order must be PAUSED to resume")
    ro["status"] = "ACTIVE"
    stamp_update(ro)
    return ro


def terminate_recurring(ro_id: str, caller_role: str, caller_id: str) -> dict:
    if ro_id not in store.recurring_orders:
        raise_error(ERR_NOT_FOUND, "Recurring order not found")
    ro = store.recurring_orders[ro_id]
    if caller_role == "Customer" and caller_id != ro["customer_id"]:
        raise_error(ERR_NOT_FOUND, "Recurring order not found")
    if ro["status"] == "TERMINATED":
        raise_error(ERR_INVALID_STATE, "Already terminated")
    ro["status"] = "TERMINATED"
    stamp_update(ro)
    return ro
