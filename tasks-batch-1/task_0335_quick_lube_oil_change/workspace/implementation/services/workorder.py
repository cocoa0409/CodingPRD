"""Work-order lifecycle, bay occupancy, queue promotion, and cascades.

Encodes the service_status x payment_status parallel state machine (PRD §3.4–§3.9),
the freed-bay promotion cascade, and the compensating invariants. State lives in
db.*; every mutation is stamped via common.touch where the PRD declares a bump.
"""
import clock
import db
from common import new_id, now_iso, stamp_create, touch, round_half_up
from errors import (
    ApiError,
    ERR_INVALID_STATE, ERR_BAY_NOT_OPEN, ERR_BAY_NOT_READY,
    ERR_TECHNICIAN_NOT_ASSIGNED, ERR_PAYMENT_NOT_SETTLED,
    ERR_BAY_CAPABILITY_MISMATCH, ERR_TECHNICIAN_CAPABILITY_MISMATCH,
    ERR_TECHNICIAN_DOUBLE_BOOKED, ERR_FLEET_ACCOUNT_INACTIVE,
    ERR_FLEET_CREDIT_EXCEEDED, ERR_VEHICLE_HAS_NO_FLEET_ACCOUNT, ERR_VALIDATION,
)
from services import pricing, fleet as fleet_svc

ASSUMED_DAILY_MILES = 40


# --------------------------------------------------------------------------
# Bay occupancy
# --------------------------------------------------------------------------

def occupy_bay(bay: dict, work_order_id: str) -> None:
    """Bay OPEN -> OCCUPIED; set back-pointer; shop.open_bay_count -= 1."""
    bay["status"] = "OCCUPIED"
    bay["current_work_order_id"] = work_order_id
    touch(bay)
    _adjust_open_bay_count(bay["shop_id"])


def free_bay(bay: dict) -> None:
    """Bay OCCUPIED -> OPEN; clear back-pointer; shop.open_bay_count += 1."""
    bay["status"] = "OPEN"
    bay["current_work_order_id"] = None
    touch(bay)
    _adjust_open_bay_count(bay["shop_id"])


def _adjust_open_bay_count(shop_id: str) -> None:
    """open_bay_count is a derived tally; recompute the shop record and bump it.

    PRD §2.4: a side-effect reconciliation independently bumps the shop's
    version and updated_at exactly as a direct mutation would.
    """
    shop = db.shops.get(shop_id)
    if shop is None:
        return
    shop["open_bay_count"] = sum(
        1 for b in db.bays.values()
        if b["shop_id"] == shop_id and b["status"] == "OPEN"
    )
    touch(shop)


# --------------------------------------------------------------------------
# Work order creation (direct + from queue promotion)
# --------------------------------------------------------------------------

def create_work_order(*, shop_id, vehicle, bay, package, odometer_in,
                      coupon_code=None, queue_ticket_id=None,
                      technician_id=None):
    """Build a DRAFT/UNPAID work order, occupy the bay, and price it."""
    wid = new_id()
    w = {
        "id": wid,
        "shop_id": shop_id,
        "vehicle_id": vehicle["id"],
        "bay_id": bay["id"],
        "package_id": package["id"],
        "technician_id": technician_id,
        "queue_ticket_id": queue_ticket_id,
        "coupon_code": coupon_code,
        "odometer_in": odometer_in,
        "service_start_at": None,
        "service_ready_at": None,
        "throughput_seconds": None,
        "throughput_breach": None,
        "package_price_cents": package["base_price_cents"],
        "lines_total_cents": 0,
        "subtotal_cents": 0,
        "coupon_discount_cents": 0,
        "fleet_discount_cents": 0,
        "total_discount_cents": 0,
        "tax_cents": 0,
        "total_cents": 0,
        "payment_method": None,
        "service_status": "DRAFT",
        "payment_status": "UNPAID",
    }
    stamp_create(w)
    db.work_orders[wid] = w
    occupy_bay(bay, wid)
    pricing.recompute_pricing(w)
    return w


# --------------------------------------------------------------------------
# Claim (technician ownership + buffered double-booking)
# --------------------------------------------------------------------------

def claim(w: dict, technician: dict) -> None:
    """Record technician_id; reject if the technician is double-booked."""
    if _technician_double_booked(technician["id"], exclude_wo_id=w["id"]):
        raise ApiError(ERR_TECHNICIAN_DOUBLE_BOOKED, 409,
                       "technician already on a live order within the buffer window")
    w["technician_id"] = technician["id"]
    touch(w)


def _technician_double_booked(technician_id: str, exclude_wo_id=None) -> bool:
    """A technician's job intervals (extended by cleanup_buffer) must not
    overlap. In logical-clock terms, any other non-terminal order already held
    by this technician collides with a new claim."""
    for w in db.work_orders.values():
        if w["id"] == exclude_wo_id:
            continue
        if w.get("technician_id") == technician_id and \
                w["service_status"] not in ("COMPLETED", "CANCELLED"):
            return True
    return False


# --------------------------------------------------------------------------
# Lines (add / remove) — version OCC handled in the route
# --------------------------------------------------------------------------

def add_line(w: dict, item: dict) -> dict:
    """Snapshot the inspection item into a new line; re-price; bump WO version."""
    lid = new_id()
    ln = {
        "id": lid,
        "work_order_id": w["id"],
        "inspection_item_id": item["id"],
        "code": item["code"],
        "price_cents": item["price_cents"],
        "labor_minutes": item["labor_minutes"],
        "voided": False,
    }
    stamp_create(ln)
    db.work_order_lines[lid] = ln
    pricing.recompute_pricing(w)
    touch(w)  # add-line bumps the order's version (OCC field) per §2.8
    return ln


def remove_line(w: dict, line: dict) -> None:
    """Remove the line and re-price (no documented version bump beyond the
    standard mutation refresh)."""
    db.work_order_lines.pop(line["id"], None)
    pricing.recompute_pricing(w)
    touch(w)


# --------------------------------------------------------------------------
# Service-status transitions
# --------------------------------------------------------------------------

def start(w: dict) -> None:
    """DRAFT -> IN_SERVICE."""
    if w["service_status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "order is not DRAFT")
    bay = db.bays.get(w["bay_id"])
    if bay is None or bay["status"] != "OCCUPIED" or \
            bay.get("current_work_order_id") != w["id"]:
        raise ApiError(ERR_BAY_NOT_READY, 409, "bay is not OCCUPIED by this order")
    if not w.get("technician_id"):
        raise ApiError(ERR_TECHNICIAN_NOT_ASSIGNED, 409, "order has not been claimed")
    package = db.service_packages[w["package_id"]]
    if package["requires_synthetic_certified_bay"]:
        if not bay["synthetic_certified"]:
            raise ApiError(ERR_BAY_CAPABILITY_MISMATCH, 409,
                           "synthetic-grade service requires a certified bay")
        technician = db.technicians[w["technician_id"]]
        if not technician["synthetic_certified"]:
            raise ApiError(ERR_TECHNICIAN_CAPABILITY_MISMATCH, 409,
                           "synthetic-grade service requires a certified technician")
    w["service_status"] = "IN_SERVICE"
    w["service_start_at"] = now_iso()
    touch(w)
    # Linked queue ticket ASSIGNED -> IN_BAY.
    if w.get("queue_ticket_id"):
        tkt = db.queue_tickets.get(w["queue_ticket_id"])
        if tkt is not None and tkt["status"] == "ASSIGNED":
            tkt["status"] = "IN_BAY"
            touch(tkt)


def begin_inspection(w: dict) -> None:
    """IN_SERVICE -> INSPECTION."""
    if w["service_status"] != "IN_SERVICE":
        raise ApiError(ERR_INVALID_STATE, 409, "order is not IN_SERVICE")
    w["service_status"] = "INSPECTION"
    touch(w)


def finish_inspection(w: dict) -> None:
    """INSPECTION -> IN_SERVICE; re-price provisional to reflect upsells."""
    if w["service_status"] != "INSPECTION":
        raise ApiError(ERR_INVALID_STATE, 409, "order is not INSPECTION")
    w["service_status"] = "IN_SERVICE"
    pricing.recompute_pricing(w)
    touch(w)


def mark_ready(w: dict) -> None:
    """IN_SERVICE -> READY; FINAL pricing; throughput."""
    if w["service_status"] != "IN_SERVICE":
        raise ApiError(ERR_INVALID_STATE, 409, "order is not IN_SERVICE")
    pricing.recompute_pricing(w)  # FINAL variant, frozen at READY
    w["service_status"] = "READY"
    ready_at = clock.now()
    w["service_ready_at"] = clock.iso(ready_at)
    start_at = clock.parse_iso(w["service_start_at"])
    elapsed = (ready_at - start_at).total_seconds()
    secs = int(elapsed)  # floor of elapsed seconds
    w["throughput_seconds"] = secs
    shop = db.shops[w["shop_id"]]
    w["throughput_breach"] = secs > shop["target_throughput_seconds"]
    touch(w)


def complete(w: dict) -> None:
    """READY -> COMPLETED; freed-bay promotion cascade; sticker; reminders."""
    if w["service_status"] != "READY":
        raise ApiError(ERR_INVALID_STATE, 409, "order is not READY")
    if w["payment_status"] != "PAID":
        raise ApiError(ERR_PAYMENT_NOT_SETTLED, 409, "payment is not PAID")
    w["service_status"] = "COMPLETED"
    touch(w)

    # [cascade] free the bay, then promote the lowest queue_seq WAITING ticket.
    bay = db.bays.get(w["bay_id"])
    if bay is not None and bay["status"] == "OCCUPIED":
        free_bay(bay)
        _promote_next_ticket(w["shop_id"], bay)

    # Sticker + vehicle reminder fields.
    _create_sticker_and_reminders(w)

    # Linked queue ticket IN_BAY -> DONE.
    if w.get("queue_ticket_id"):
        tkt = db.queue_tickets.get(w["queue_ticket_id"])
        if tkt is not None and tkt["status"] == "IN_BAY":
            tkt["status"] = "DONE"
            touch(tkt)


def cancel(w: dict) -> None:
    """DRAFT/IN_SERVICE/INSPECTION -> CANCELLED; void lines/payment; free bay."""
    if w["service_status"] not in ("DRAFT", "IN_SERVICE", "INSPECTION"):
        raise ApiError(ERR_INVALID_STATE, 409, "order cannot be cancelled in its current state")
    w["service_status"] = "CANCELLED"

    # Void all lines; lines_total recomputed to 0.
    for ln in db.work_order_lines.values():
        if ln["work_order_id"] == w["id"] and not ln["voided"]:
            ln["voided"] = True
            touch(ln)

    # Compensating payment void (releases fleet reserved credit via recompute).
    if w["payment_status"] == "AUTHORIZED":
        _void_payment_record(w)
        w["payment_status"] = "VOIDED"

    pricing.recompute_pricing(w)
    touch(w)

    # Free the bay.
    bay = db.bays.get(w["bay_id"])
    if bay is not None and bay["status"] == "OCCUPIED" and \
            bay.get("current_work_order_id") == w["id"]:
        free_bay(bay)

    # Linked queue ticket -> CANCELLED.
    if w.get("queue_ticket_id"):
        tkt = db.queue_tickets.get(w["queue_ticket_id"])
        if tkt is not None and tkt["status"] not in ("DONE", "CANCELLED"):
            tkt["status"] = "CANCELLED"
            touch(tkt)


def _promote_next_ticket(shop_id: str, bay: dict) -> None:
    """Pull the lowest queue_seq WAITING ticket forward onto the freed bay."""
    waiting = [t for t in db.queue_tickets.values()
               if t["shop_id"] == shop_id and t["status"] == "WAITING"]
    if not waiting:
        return
    tkt = min(waiting, key=lambda t: t["queue_seq"])
    vehicle = db.vehicles[tkt["vehicle_id"]]
    package = db.service_packages[tkt["requested_package_id"]]
    new_wo = create_work_order(
        shop_id=shop_id, vehicle=vehicle, bay=bay, package=package,
        odometer_in=vehicle["odometer"], queue_ticket_id=tkt["id"],
    )
    tkt["status"] = "ASSIGNED"
    tkt["assigned_bay_id"] = bay["id"]
    tkt["work_order_id"] = new_wo["id"]
    touch(tkt)


# --------------------------------------------------------------------------
# Payment dimension
# --------------------------------------------------------------------------

def authorize(w: dict, payment_method) -> None:
    """UNPAID -> AUTHORIZED (creates Payment; fleet credit gate)."""
    # priority 5: state check first (service_status meaningful for a total).
    if w["service_status"] not in ("INSPECTION", "READY"):
        raise ApiError(ERR_INVALID_STATE, 409, "order is not INSPECTION or READY")
    if w["payment_status"] != "UNPAID":
        raise ApiError(ERR_INVALID_STATE, 409, "payment is not UNPAID")
    # priority (body): payment_method must be a valid enum.
    if payment_method not in ("CARD", "CASH", "FLEET_ACCOUNT"):
        raise ApiError(ERR_VALIDATION, 400, "payment_method is missing or invalid")

    fleet_acct = None
    if payment_method == "FLEET_ACCOUNT":
        vehicle = db.vehicles[w["vehicle_id"]]
        if not vehicle.get("fleet_account_id"):
            raise ApiError(ERR_VEHICLE_HAS_NO_FLEET_ACCOUNT, 404,
                           "vehicle has no fleet account")
        fleet_acct = db.fleet_accounts.get(vehicle["fleet_account_id"])
        if fleet_acct is None or fleet_acct["status"] != "ACTIVE":
            raise ApiError(ERR_FLEET_ACCOUNT_INACTIVE, 409, "fleet account is not ACTIVE")
        # priority 10 (fiscal): reserved + this total must fit the limit.
        reserved = fleet_svc.reserved_credit(fleet_acct["id"])
        if reserved + w["total_cents"] > fleet_acct["credit_limit_cents"]:
            raise ApiError(ERR_FLEET_CREDIT_EXCEEDED, 402, "fleet credit limit exceeded")

    w["payment_method"] = payment_method
    w["payment_status"] = "AUTHORIZED"
    touch(w)

    pid = new_id()
    payment = {
        "id": pid,
        "work_order_id": w["id"],
        "method": payment_method,
        "amount_cents": w["total_cents"],
        "status": "AUTHORIZED",
    }
    stamp_create(payment)
    db.payments[pid] = payment

    if fleet_acct is not None:
        touch(fleet_acct)  # reserved_credit recomputed; reconciliation bump


def capture_payment(w: dict) -> None:
    """AUTHORIZED -> PAID."""
    if w["payment_status"] != "AUTHORIZED":
        raise ApiError(ERR_INVALID_STATE, 409, "payment is not AUTHORIZED")
    if w["service_status"] != "READY":
        raise ApiError(ERR_INVALID_STATE, 409, "service is not READY")
    payment = _active_payment(w)
    if payment is not None:
        payment["status"] = "CAPTURED"
        touch(payment)
    w["payment_status"] = "PAID"
    touch(w)

    # Coupon redemption: recompute redeemed_count; exhaust at the limit.
    if w.get("coupon_code"):
        coupon = pricing.find_coupon(w["coupon_code"], w["shop_id"])
        if coupon is not None:
            redeemed = fleet_svc.coupon_redeemed_count(coupon["code"], coupon["shop_id"])
            if coupon["status"] == "ACTIVE" and redeemed >= coupon["usage_limit"]:
                coupon["status"] = "EXHAUSTED"
            touch(coupon)

    vehicle = db.vehicles[w["vehicle_id"]]
    if vehicle.get("fleet_account_id"):
        fleet_acct = db.fleet_accounts.get(vehicle["fleet_account_id"])
        if fleet_acct is not None:
            touch(fleet_acct)  # settled_credit recomputed


def void_payment(w: dict) -> None:
    """AUTHORIZED -> VOIDED (compensating; releases reserved credit)."""
    if w["payment_status"] != "AUTHORIZED":
        raise ApiError(ERR_INVALID_STATE, 409, "payment is not AUTHORIZED")
    _void_payment_record(w)
    w["payment_status"] = "VOIDED"
    touch(w)


def _void_payment_record(w: dict) -> None:
    payment = _active_payment(w)
    if payment is not None:
        payment["status"] = "VOIDED"
        touch(payment)
    vehicle = db.vehicles[w["vehicle_id"]]
    if vehicle.get("fleet_account_id"):
        fleet_acct = db.fleet_accounts.get(vehicle["fleet_account_id"])
        if fleet_acct is not None:
            touch(fleet_acct)  # reserved_credit recomputed (released)


def _active_payment(w: dict):
    candidates = [p for p in db.payments.values()
                  if p["work_order_id"] == w["id"] and p["status"] == "AUTHORIZED"]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p["created_at"])


# --------------------------------------------------------------------------
# Next-service projection (sticker + vehicle reminders)  (PRD §3.10)
# --------------------------------------------------------------------------

def _create_sticker_and_reminders(w: dict) -> None:
    import math
    package = db.service_packages[w["package_id"]]
    vehicle = db.vehicles[w["vehicle_id"]]
    completed_at = clock.now()

    service_odometer = w["odometer_in"]
    next_service_odometer = service_odometer + package["interval_miles"]
    next_service_date_dt = _add_days(completed_at, package["interval_days"])
    next_service_date = clock.iso(next_service_date_dt)

    projected_days_for_miles = math.ceil(package["interval_miles"] / ASSUMED_DAILY_MILES)
    basis = "MILEAGE" if projected_days_for_miles <= package["interval_days"] else "TIME"

    sid = new_id()
    sticker = {
        "id": sid,
        "work_order_id": w["id"],
        "vehicle_id": w["vehicle_id"],
        "service_odometer": service_odometer,
        "next_service_odometer": next_service_odometer,
        "next_service_date": next_service_date,
        "basis": basis,
    }
    stamp_create(sticker, with_common=False)
    db.service_stickers[sid] = sticker

    # Vehicle reminder fields from the most recent COMPLETED order (this one).
    vehicle["last_service_odometer"] = w["odometer_in"]
    vehicle["last_service_date"] = w["created_at"]
    vehicle["next_service_odometer"] = w["odometer_in"] + package["interval_miles"]
    last_dt = clock.parse_iso(w["created_at"])
    vehicle["next_service_date"] = clock.iso(_add_days(last_dt, package["interval_days"]))
    touch(vehicle)


def _add_days(dt, days: int):
    from datetime import timedelta
    return dt + timedelta(days=days)
