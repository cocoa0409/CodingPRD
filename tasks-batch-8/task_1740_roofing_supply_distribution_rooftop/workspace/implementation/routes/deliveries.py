"""Delivery scheduling and the dispatch-day transition chain (PRD 3.5)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_ORDER_NOT_FOUND,
    ERR_DELIVERY_NOT_FOUND,
    ERR_SLOT_NOT_FOUND,
    ERR_ORDER_NOT_CONFIRMED,
    ERR_DELIVERY_NOT_SCHEDULED,
    ERR_DELIVERY_NOT_EN_ROUTE,
    ERR_DELIVERY_NOT_FAILED,
    ERR_DELIVERY_NOT_RESCHEDULED,
    ERR_SLOT_FULL,
    ERR_INVALID_REQUEST,
)
from middleware import authorized, check_contractor_owns
from routes.helpers import body, body_field, render_list, render_one
from services.core import create_record, get_or_404, mutate
from services.calculations import delivery_fee, order_lines_of
from services.order_ops import recompute_fulfillment

bp = Blueprint("deliveries", __name__)

DELIVERY_READ_ROLES = ["PlatformAdmin", "BranchManager", "Dispatcher", "Contractor", "ClaimsAdjuster"]
EQUIPMENT_TYPES = ("GROUND", "ROOFTOP_CONVEYOR", "CRANE")


def _order_or_404(rid):
    return get_or_404("orders", rid, ERR_ORDER_NOT_FOUND)


def _delivery_or_404(rid):
    return get_or_404("deliveries", rid, ERR_DELIVERY_NOT_FOUND)


def _slot_or_404(rid):
    return get_or_404("delivery_slots", rid, ERR_SLOT_NOT_FOUND)


def _check_slot_compatible(slot, equipment_type):
    """Priority 8: equipment must match and the slot must have room; both
    surface as ERR_SLOT_FULL (PRD 3.5)."""
    if slot["equipment_type"] != equipment_type:
        raise_error(ERR_SLOT_FULL, "delivery equipment_type must match the slot's equipment_type")
    if slot["booked_count"] >= slot["capacity"]:
        raise_error(ERR_SLOT_FULL, "delivery slot is at capacity")


def _refresh_order_total(order):
    order["total_cents"] = (order["subtotal_cents"] - order["discount_cents"]
                            + order["surge_premium_cents"] + order["delivery_fee_cents"])


def _adjust_pending_hold(order, fee_delta):
    """pending_delivery_hold_cents tracks CONFIRMED-but-not-yet-INVOICED order
    totals, so fee accrual/removal on a CONFIRMED order moves the hold. On a
    QUOTED order no hold exists yet; the fee is priced in at confirmation."""
    if order["status"] != "CONFIRMED" or fee_delta == 0:
        return
    job = db["job_accounts"].get(order["job_account_id"])
    account = db["contractor_accounts"].get(job["contractor_account_id"]) if job else None
    if account is not None:
        account["pending_delivery_hold_cents"] += fee_delta
        mutate(account)


# ---------------------------------------------------------------------------
# Scheduling and reads
# ---------------------------------------------------------------------------

@bp.post("/roofing/orders/<rid>/deliveries")
def schedule_delivery(rid):
    authorized(["Dispatcher"])
    order = _order_or_404(rid)
    data = body()
    slot = _slot_or_404(body_field(data, "delivery_slot_id", required=True))
    equipment_type = body_field(data, "equipment_type", required=True)
    if equipment_type not in EQUIPMENT_TYPES:
        raise_error(ERR_INVALID_REQUEST, "equipment_type must be GROUND, ROOFTOP_CONVEYOR or CRANE")
    if order["status"] not in ("QUOTED", "CONFIRMED"):
        raise_error(ERR_ORDER_NOT_CONFIRMED,
                    "deliveries schedule against orders in QUOTED or CONFIRMED")
    _check_slot_compatible(slot, equipment_type)

    # The delivery covers each line's remaining undelivered quantity; the
    # snapshot prices the fee at scheduling time (PRD 3.5).
    line_quantities = {}
    for line in order_lines_of(order["id"]):
        remaining = line["quantity_bundles"] - line["delivered_bundles"]
        if remaining > 0:
            line_quantities[line["id"]] = remaining
    bundle_count = sum(line_quantities.values())
    fee, crane_fee = delivery_fee(equipment_type, bundle_count)

    rec = create_record("deliveries", {
        "order_id": order["id"],
        "delivery_slot_id": slot["id"],
        "equipment_type": equipment_type,
        "bundle_count": bundle_count,
        "fee_cents": fee,
        "crane_fee_cents": crane_fee,
        "attempt_count": 0,
        "delivered_at": None,
        "status": "SCHEDULED",
    })
    rec["_line_quantities"] = line_quantities

    slot["booked_count"] += 1
    mutate(slot)
    order["delivery_fee_cents"] += fee
    _refresh_order_total(order)
    mutate(order)
    _adjust_pending_hold(order, fee)
    return render_one("deliveries", rec, status=201)


@bp.get("/roofing/orders/<rid>/deliveries")
def list_order_deliveries(rid):
    caller = authorized(DELIVERY_READ_ROLES)
    order = _order_or_404(rid)
    job = db["job_accounts"].get(order["job_account_id"])
    check_contractor_owns(caller, job["contractor_account_id"] if job else None)
    deliveries = [d for d in db["deliveries"].values() if d["order_id"] == order["id"]]
    return render_list(caller, "deliveries", base_records=deliveries)


@bp.get("/roofing/deliveries")
def list_deliveries():
    caller = authorized(DELIVERY_READ_ROLES)
    return render_list(caller, "deliveries",
                       filters={"delivery_slot_id": request.args.get("delivery_slot_id"),
                                "status": request.args.get("status")})


@bp.get("/roofing/deliveries/<rid>")
def get_delivery(rid):
    caller = authorized(DELIVERY_READ_ROLES)
    rec = _delivery_or_404(rid)
    order = db["orders"].get(rec["order_id"])
    job = db["job_accounts"].get(order["job_account_id"]) if order else None
    check_contractor_owns(caller, job["contractor_account_id"] if job else None)
    return render_one("deliveries", rec)


# ---------------------------------------------------------------------------
# Dispatch-day transitions
# ---------------------------------------------------------------------------

@bp.post("/roofing/deliveries/<rid>/dispatch")
def dispatch_delivery(rid):
    authorized(["Dispatcher"])
    rec = _delivery_or_404(rid)
    order = db["orders"].get(rec["order_id"])
    if rec["status"] != "SCHEDULED":
        raise_error(ERR_DELIVERY_NOT_SCHEDULED, "dispatch requires the delivery to be SCHEDULED")
    if order is None or order["status"] != "CONFIRMED":
        raise_error(ERR_ORDER_NOT_CONFIRMED, "dispatch requires the parent order CONFIRMED")
    rec["attempt_count"] += 1
    rec["status"] = "EN_ROUTE"
    # Reservation becomes a physical draw: both counters drop per covered line.
    for line_id, qty in rec.get("_line_quantities", {}).items():
        line = db["order_lines"].get(line_id)
        lot = db["inventory_lots"].get(line["inventory_lot_id"]) if line else None
        if lot is not None:
            lot["on_hand_bundles"] -= qty
            lot["reserved_bundles"] -= qty
            mutate(lot)
    mutate(rec)
    return render_one("deliveries", rec)


@bp.post("/roofing/deliveries/<rid>/complete")
def complete_delivery(rid):
    from util import CLOCK
    authorized(["Dispatcher"])
    rec = _delivery_or_404(rid)
    if rec["status"] != "EN_ROUTE":
        raise_error(ERR_DELIVERY_NOT_EN_ROUTE, "complete requires the delivery to be EN_ROUTE")
    order = db["orders"].get(rec["order_id"])
    rec["status"] = "DELIVERED"
    rec["delivered_at"] = CLOCK.now_ts()
    for line_id, qty in rec.get("_line_quantities", {}).items():
        line = db["order_lines"].get(line_id)
        if line is not None:
            line["delivered_bundles"] += qty
            mutate(line)
    if order is not None:
        recompute_fulfillment(order)
        mutate(order)
    slot = db["delivery_slots"].get(rec["delivery_slot_id"])
    if slot is not None:
        slot["booked_count"] -= 1
        mutate(slot)
    mutate(rec)
    return render_one("deliveries", rec)


@bp.post("/roofing/deliveries/<rid>/fail")
def fail_delivery(rid):
    authorized(["Dispatcher"])
    rec = _delivery_or_404(rid)
    if rec["status"] != "EN_ROUTE":
        raise_error(ERR_DELIVERY_NOT_EN_ROUTE, "fail requires the delivery to be EN_ROUTE")
    rec["status"] = "FAILED"
    # Inventory restored: the attempted quantity returns to both counters.
    for line_id, qty in rec.get("_line_quantities", {}).items():
        line = db["order_lines"].get(line_id)
        lot = db["inventory_lots"].get(line["inventory_lot_id"]) if line else None
        if lot is not None:
            lot["on_hand_bundles"] += qty
            lot["reserved_bundles"] += qty
            mutate(lot)
    mutate(rec)
    return render_one("deliveries", rec)


@bp.post("/roofing/deliveries/<rid>/reschedule")
def reschedule_delivery(rid):
    authorized(["Dispatcher"])
    rec = _delivery_or_404(rid)
    if rec["status"] != "FAILED":
        raise_error(ERR_DELIVERY_NOT_FAILED, "reschedule requires the delivery to be FAILED")
    data = body()
    new_slot = _slot_or_404(body_field(data, "delivery_slot_id", required=True))
    _check_slot_compatible(new_slot, rec["equipment_type"])
    order = db["orders"].get(rec["order_id"])

    old_slot = db["delivery_slots"].get(rec["delivery_slot_id"])
    if old_slot is not None:
        old_slot["booked_count"] -= 1
        mutate(old_slot)
    new_slot["booked_count"] += 1
    mutate(new_slot)
    rec["delivery_slot_id"] = new_slot["id"]
    rec["status"] = "RESCHEDULED"

    new_fee, crane_fee = delivery_fee(rec["equipment_type"], rec["bundle_count"])
    if order is not None:
        order["delivery_fee_cents"] += (new_fee - rec["fee_cents"])
        _refresh_order_total(order)
        mutate(order)
        _adjust_pending_hold(order, new_fee - rec["fee_cents"])
    rec["fee_cents"] = new_fee
    rec["crane_fee_cents"] = crane_fee
    mutate(rec)
    return render_one("deliveries", rec)


@bp.post("/roofing/deliveries/<rid>/reconfirm")
def reconfirm_delivery(rid):
    authorized(["Dispatcher"])
    rec = _delivery_or_404(rid)
    if rec["status"] != "RESCHEDULED":
        raise_error(ERR_DELIVERY_NOT_RESCHEDULED, "reconfirm requires the delivery to be RESCHEDULED")
    rec["status"] = "SCHEDULED"
    mutate(rec)
    return render_one("deliveries", rec)


@bp.post("/roofing/deliveries/<rid>/cancel")
def cancel_delivery(rid):
    authorized(["Dispatcher"])
    rec = _delivery_or_404(rid)
    if rec["status"] != "SCHEDULED":
        raise_error(ERR_DELIVERY_NOT_SCHEDULED, "cancel requires the delivery to be SCHEDULED")
    rec["status"] = "CANCELLED"
    slot = db["delivery_slots"].get(rec["delivery_slot_id"])
    if slot is not None:
        slot["booked_count"] -= 1
        mutate(slot)
    order = db["orders"].get(rec["order_id"])
    if order is not None:
        order["delivery_fee_cents"] -= rec["fee_cents"]
        _refresh_order_total(order)
        mutate(order)
        _adjust_pending_hold(order, -rec["fee_cents"])
    mutate(rec)
    return render_one("deliveries", rec)
