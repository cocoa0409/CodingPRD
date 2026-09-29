"""Implant lot / reservation arithmetic (PRD 3.7)."""
from decimal import Decimal

from db import db, touch
from errors import ApiError
from services.domain import (CONSIGNMENT_CREDIT_RATE, DIAMETER_TOLERANCE_MM,
                             LENGTH_TOLERANCE_MM, RESTOCKING_TIERS, get_lot,
                             get_practice, ordered, reservations_of_lot)
from services.practice import recompute_consignment, touch_practice
from timeutil import dec, parse_date, rcents


def restocking_rate(subtotal_cents):
    """Tiered rate chosen from the pinned line subtotal."""
    for ceiling, rate in RESTOCKING_TIERS:
        if ceiling is None or subtotal_cents <= ceiling:
            return rate
    return RESTOCKING_TIERS[-1][1]


def restocking_fee(subtotal_cents):
    return rcents(Decimal(subtotal_cents) * restocking_rate(subtotal_cents))


def consignment_credit(lot, subtotal_cents):
    if not lot.get("is_consignment"):
        return 0
    return rcents(Decimal(subtotal_cents) * CONSIGNMENT_CREDIT_RATE)


def liability_for(status, subtotal_cents, fee_cents, credit_cents):
    if status in ("HELD", "CONSUMED"):
        return subtotal_cents - credit_cents
    if status == "RELEASED":
        return fee_cents
    if status == "SHORTED":
        return subtotal_cents
    return 0


def recompute_lot(lot):
    """quantity_reserved is the sum of HELD quantities; available never goes negative."""
    reserved = 0
    for reservation in reservations_of_lot(lot["id"]):
        if reservation["status"] == "HELD":
            reserved += int(reservation["quantity"])
    lot["quantity_reserved"] = reserved
    if lot["status"] == "QUARANTINED":
        lot["available_quantity"] = 0
    else:
        lot["available_quantity"] = max(0, int(lot["quantity_on_hand"]) - reserved)
    return lot


def lot_practice(lot):
    return get_practice(lot["practice_id"])


def sync_practice_exposure(practice):
    if practice is None:
        return
    recompute_consignment(practice)
    touch_practice(practice)


def hold_pricing(lot, quantity):
    """PRD 3.7: pricing is pinned at creation and creation "computes all four money
    fields", so the tiered restocking fee is stamped while the row is still HELD."""
    subtotal = int(lot["unit_cost_cents"]) * int(quantity)
    credit = consignment_credit(lot, subtotal)
    fee = restocking_fee(subtotal)
    return {
        "line_subtotal_cents": subtotal,
        "restocking_fee_cents": fee,
        "consignment_credit_cents": credit,
        "consignment_liability_cents": liability_for("HELD", subtotal, fee, credit),
    }


def projected_liability(lot, quantity):
    pricing = hold_pricing(lot, quantity)
    return pricing["consignment_liability_cents"]


def credit_limit_check(practice, added_liability):
    exposure = int(practice.get("consignment_committed_cents") or 0) + int(added_liability)
    if exposure > int(practice.get("consignment_credit_limit_cents") or 0):
        raise ApiError("ERR_CONSIGNMENT_CREDIT_LIMIT_EXCEEDED")


def release_reservation(reservation, waive_fee=False, touch_row=True):
    """HELD -> RELEASED: quantity_on_hand untouched, tiered fee charged, credit reset."""
    subtotal = int(reservation["line_subtotal_cents"])
    fee = 0 if waive_fee else restocking_fee(subtotal)
    reservation["status"] = "RELEASED"
    reservation["restocking_fee_cents"] = fee
    reservation["consignment_credit_cents"] = 0
    reservation["consignment_liability_cents"] = liability_for("RELEASED", subtotal, fee, 0)
    if touch_row:
        touch(reservation)
    lot = get_lot(reservation["lot_id"])
    if lot is not None:
        recompute_lot(lot)
        touch(lot)
    return reservation


def short_reservation(reservation):
    """HELD -> SHORTED: physical stock disappears, no fee, no credit."""
    subtotal = int(reservation["line_subtotal_cents"])
    reservation["status"] = "SHORTED"
    reservation["restocking_fee_cents"] = 0
    reservation["consignment_credit_cents"] = 0
    reservation["consignment_liability_cents"] = liability_for("SHORTED", subtotal, 0, 0)
    touch(reservation)
    lot = get_lot(reservation["lot_id"])
    if lot is not None:
        lot["quantity_on_hand"] = max(0, int(lot["quantity_on_hand"]) - int(reservation["quantity"]))
        recompute_lot(lot)
        touch(lot)
    return reservation


def consume_reservation(reservation):
    """HELD -> CONSUMED: both counters fall, liability keeps the credit."""
    subtotal = int(reservation["line_subtotal_cents"])
    credit = int(reservation["consignment_credit_cents"] or 0)
    reservation["status"] = "CONSUMED"
    reservation["consignment_liability_cents"] = liability_for("CONSUMED", subtotal, 0, credit)
    touch(reservation)
    lot = get_lot(reservation["lot_id"])
    if lot is not None:
        lot["quantity_on_hand"] = max(0, int(lot["quantity_on_hand"]) - int(reservation["quantity"]))
        recompute_lot(lot)
        touch(lot)
    return reservation


def within_tolerance(lot, diameter, length):
    d_ok = abs(dec(lot["diameter_mm"]) - dec(diameter)) <= DIAMETER_TOLERANCE_MM
    l_ok = abs(dec(lot["length_mm"]) - dec(length)) <= LENGTH_TOLERANCE_MM
    return d_ok and l_ok


def auto_size_select(case, diameter, length, quantity):
    """calculations.implant_auto_size_selection - deterministic candidate ordering."""
    planned_start = parse_date(case["planned_start"])
    pool = []
    quarantined_match = False
    for lot in db.lots.values():
        if lot["practice_id"] != case["practice_id"]:
            continue
        if not within_tolerance(lot, diameter, length):
            continue
        expiry = parse_date(lot["expiry_date"])
        if expiry is None or expiry <= planned_start:
            continue
        if lot["status"] == "QUARANTINED":
            quarantined_match = True
            continue
        if lot["status"] != "AVAILABLE":
            continue
        if int(lot["available_quantity"]) < int(quantity):
            continue
        pool.append(lot)
    if not pool:
        if quarantined_match:
            raise ApiError("ERR_LOT_UNAVAILABLE")
        raise ApiError("ERR_NO_ELIGIBLE_IMPLANT_LOT")
    pool.sort(key=lambda l: (dec(l["diameter_mm"]), dec(l["length_mm"]),
                             parse_date(l["expiry_date"]), l["created_at"], l["_seq"]))
    return pool[0]
