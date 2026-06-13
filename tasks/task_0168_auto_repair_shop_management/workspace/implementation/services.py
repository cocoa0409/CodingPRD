"""Domain services: line creation, cascades, warranty window, totals.

Centralizes logic shared by direct endpoints and the recommended-job
materialization cascade (PRD 3.4, 3.5, 3.8, 3.11, 3.12).
"""
from datetime import timedelta

import db
from calculations import (
    labor_charge_cents,
    parts_extended_charge_cents,
    recompute_repair_order_total,
)
from clock import now, parse_iso
from errors import ApiError

WARRANTY_DAYS = 90
WARRANTY_MILES = 4000
CLEANUP_BUFFER_MINUTES = 10

RO_NON_EDITABLE = {"COMPLETED", "INVOICED", "CLOSED", "CANCELLED"}


# --------------------------------------------------------------------------- #
# Warranty window (PRD 3.8 / SCAFFOLD warranty_comeback_window)
# --------------------------------------------------------------------------- #
def check_warranty_window(original_ro, comeback_vehicle):
    """Validate a comeback is within the warranty window. Raise on expiry.

    within iff BOTH:
      now <= original.closed_at + 90 days        (inclusive)
      comeback.vehicle.odometer_miles <= original.close_odometer_miles + 4000 (inclusive)
    Original must be CLOSED (closed_at + close_odometer_miles set).
    """
    closed_at = original_ro.get("closed_at")
    close_odo = original_ro.get("close_odometer_miles")
    if closed_at is None or close_odo is None:
        # Original not CLOSED -> there is no valid warranty anchor.
        raise ApiError("ERR_WARRANTY_EXPIRED",
                       "Original repair order is not closed; no warranty anchor.")
    deadline = parse_iso(closed_at) + timedelta(days=WARRANTY_DAYS)
    if now() > deadline:
        raise ApiError("ERR_WARRANTY_EXPIRED", "Warranty time window exceeded.")
    if comeback_vehicle["odometer_miles"] > close_odo + WARRANTY_MILES:
        raise ApiError("ERR_WARRANTY_EXPIRED", "Warranty mileage window exceeded.")


# --------------------------------------------------------------------------- #
# Labor line creation (PRD 3.4)
# --------------------------------------------------------------------------- #
def create_labor_line(ro, labor_operation_id, technician_id, billing_method,
                      rate_cents, is_warranty):
    op = db.labor_operations[labor_operation_id]
    line = db.common_fields()
    line.update({
        "repair_order_id": ro["id"],
        "labor_operation_id": labor_operation_id,
        "technician_id": technician_id,
        "billing_method": billing_method,
        "book_hours": op["book_hours"],          # snapshot at creation
        "rate_cents": rate_cents,
        "actual_hours": 0,
        "open_clock_at": None,
        "is_warranty": is_warranty,
        "charge_cents": 0,
        "status": "NOT_STARTED",
    })
    line["charge_cents"] = labor_charge_cents(line)
    db.labor_lines[line["id"]] = line
    recompute_repair_order_total(ro)
    return line


# --------------------------------------------------------------------------- #
# Part line creation + core cascade (PRD 3.5, 3.12)
# --------------------------------------------------------------------------- #
def create_part_line(ro, part_number, description, quantity, unit_cost_cents,
                     markup_mode, has_core, core_deposit_cents, is_warranty):
    # parts_markup may raise ERR_MARKUP_TIER_MISSING; compute before persisting.
    extended = parts_extended_charge_cents(quantity, unit_cost_cents, markup_mode,
                                           is_warranty)
    line = db.common_fields()
    line.update({
        "repair_order_id": ro["id"],
        "part_number": part_number,
        "description": description,
        "quantity": quantity,
        "unit_cost_cents": unit_cost_cents,
        "markup_mode": markup_mode,
        "has_core": has_core,
        "core_deposit_cents": core_deposit_cents,
        "is_warranty": is_warranty,
        "extended_charge_cents": extended,
        "status": "QUOTED",
    })
    db.part_lines[line["id"]] = line

    if has_core:
        _create_core_charge(ro, line)

    recompute_repair_order_total(ro)
    return line


def _create_core_charge(ro, part_line):
    """Cascade a CoreCharge (CHARGED) for a part line carrying a core (PRD 3.12).

    deposit_cents = part_line.quantity * part_line.core_deposit_cents.
    Adds the deposit to RO.core_deposit_total_cents (conserved quantity,
    maintained incrementally — see calculations.recompute_repair_order_total).
    """
    deposit = part_line["quantity"] * part_line["core_deposit_cents"]
    cc = db.common_fields()
    cc.update({
        "repair_order_id": ro["id"],
        "part_line_id": part_line["id"],
        "deposit_cents": deposit,
        "refunded_cents": 0,
        "status": "CHARGED",
    })
    db.core_charges[cc["id"]] = cc
    ro["core_deposit_total_cents"] += deposit
    return cc
