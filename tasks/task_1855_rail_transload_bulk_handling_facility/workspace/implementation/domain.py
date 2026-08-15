"""Business logic: calculations, cascades, and shared entity operations.

Implements the calculation rules of PRD 2.5-2.6 and 3.x: demurrage accrual
(tiered, constructive/actual basis), SIT accrual (calendar/business), the
contamination risk score (strict matrix / weighted score), the switching-fee
allowance sequencing, the cleaning fee schedule, the invoice sweep, and the
safety posture threshold machine with its suspend/resume cascades.
"""

import math
from datetime import timedelta
from decimal import Decimal

from db import STORE, new_entity, touch, public, now, iso
from util import (
    dec, tons_add, tons_sub, rhu_cents, floor_minutes, floor_days,
    parse_datetime, same_utc_month,
)

# --- Calculation constants (SCAFFOLD calculations[].constants) ---
TIER1_DAYS = 3
TIER1_RATE = 7500
TIER2_DAYS = 4
TIER2_RATE = 15000
TIER3_RATE = 25000

BLOCK_THRESHOLD = 100

BASE_SPOT_FEE = 18500
BASE_PULL_FEE = 20500

RINSE_FEE = 250000
DETERGENT_FEE = 600000
STEAM_FEE = 1200000
CLEANING_FEES = {"RINSE": RINSE_FEE, "DETERGENT": DETERGENT_FEE, "STEAM": STEAM_FEE}

SUSPEND_INCIDENT_COUNT = 3

PULL_WINDOW_MINUTES = 30

OCCUPIED_PLACEMENTS = {
    "SPOTTED", "IN_TRANSFER", "EMPTY_AWAITING_CLEANING", "CLEANING",
    "READY_FOR_RELEASE",
}

CREDIT_MULTS = {
    "GOOD_STANDING": Decimal("1"),
    "CREDIT_WATCH": Decimal("1.25"),
    "CREDIT_HOLD": Decimal("1.5"),
}


def current_facility():
    """The singleton facility (first created); None before any exists."""
    facs = sorted(STORE.facilities.values(), key=lambda f: f["_seq"])
    return facs[0] if facs else None


def facility_config():
    fac = current_facility()
    if fac is None:
        return {
            "free_demurrage_hours": 48,
            "sit_free_days": 2,
            "switch_buffer_minutes": 30,
            "free_switches_per_period": 0,
            "contamination_policy": "STRICT_MATRIX",
        }
    return fac


# =============================================================================
# Safety posture (calculations.safety_posture)
# =============================================================================

def recompute_posture():
    """Recompute the global posture from open incidents; mirror it onto every
    facility (bumping Facility.version only when the posture value changes);
    run the suspend/resume transfer-order cascades on SUSPENDED transitions."""
    open_incidents = [i for i in STORE.incidents.values() if i["status"] == "OPEN"]
    n = len(open_incidents)
    if any(i["severity"] == "CRITICAL" for i in open_incidents) or n >= SUSPEND_INCIDENT_COUNT:
        new = "SUSPENDED"
    elif n >= 1:
        new = "ELEVATED"
    else:
        new = "NORMAL"
    old = STORE.posture
    STORE.posture = new
    for fac in STORE.facilities.values():
        fac["open_incident_count"] = n
        if fac["safety_posture"] != new:
            fac["safety_posture"] = new
            touch(fac)
    if new == "SUSPENDED" and old != "SUSPENDED":
        _suspend_cascade()
    elif old == "SUSPENDED" and new != "SUSPENDED":
        _resume_cascade()


def _suspend_cascade():
    """Every ACTIVE transfer order -> SUSPENDED: release its equipment and
    pause its railcar."""
    for order in STORE.transfer_orders.values():
        if order["status"] != "ACTIVE":
            continue
        eq = STORE.equipment[order["equipment_id"]]
        if eq["status"] == "IN_USE":
            eq["status"] = "AVAILABLE"
            touch(eq)
        car = STORE.railcars[order["railcar_id"]]
        if car["placement_status"] == "IN_TRANSFER":
            car["placement_status"] = "SPOTTED"
            touch(car)
        order["status"] = "SUSPENDED"
        touch(order)


def _resume_cascade():
    """Every SUSPENDED transfer order -> ACTIVE: re-acquire its equipment and
    resume its railcar."""
    for order in STORE.transfer_orders.values():
        if order["status"] != "SUSPENDED":
            continue
        eq = STORE.equipment[order["equipment_id"]]
        car = STORE.railcars[order["railcar_id"]]
        if eq["status"] == "AVAILABLE":
            eq["status"] = "IN_USE"
            eq["last_product_id"] = car["product_id"]
            touch(eq)
        if car["placement_status"] == "SPOTTED":
            car["placement_status"] = "IN_TRANSFER"
            touch(car)
        order["status"] = "ACTIVE"
        touch(order)


# =============================================================================
# Demurrage (calculations.demurrage_accrual)
# =============================================================================

def demurrage_accrual(car):
    """Provisional (end = logical clock) or final (end = released_timestamp)
    demurrage: returns (billable_days, amount_cents)."""
    cust = STORE.customers[car["customer_id"]]
    if cust["demurrage_basis"] == "CONSTRUCTIVE":
        start_raw = car["arrival_timestamp"]
    else:
        start_raw = car["placed_timestamp"]
    if not start_raw:
        return 0, 0
    start = parse_datetime(start_raw)
    end = parse_datetime(car["released_timestamp"]) if car["released_timestamp"] else now()
    elapsed_min = floor_minutes(end - start)
    free_min = facility_config()["free_demurrage_hours"] * 60
    billable_min = max(0, elapsed_min - free_min)
    days = math.ceil(billable_min / 1440) if billable_min > 0 else 0
    tiered = (
        TIER1_RATE * min(days, TIER1_DAYS)
        + TIER2_RATE * min(max(days - TIER1_DAYS, 0), TIER2_DAYS)
        + TIER3_RATE * max(days - TIER1_DAYS - TIER2_DAYS, 0)
    )
    prod = STORE.products[car["product_id"]]
    hazard = Decimal("1.5") if prod["hazard_class"] == "HAZARDOUS" else Decimal("1")
    credit = CREDIT_MULTS[cust["credit_standing"]]
    amount = rhu_cents(Decimal(tiered) * hazard * credit)
    return days, amount


# =============================================================================
# Storage-in-transit (calculations.sit_accrual)
# =============================================================================

def sit_accrual(lot):
    """Provisional (end = logical clock) or final (end = close_timestamp) SIT:
    returns (billable_days, amount_cents)."""
    start = parse_datetime(lot["sit_start_timestamp"])
    window_start = start + timedelta(days=lot["sit_free_days"])
    end = parse_datetime(lot["close_timestamp"]) if lot["close_timestamp"] else now()
    whole = floor_days(end - window_start)
    if lot["sit_day_basis"] == "BUSINESS":
        days = sum(
            1
            for k in range(whole)
            if (window_start + timedelta(days=k)).weekday() < 5
        )
    else:
        days = whole
    return days, days * lot["sit_daily_rate_cents"]


# =============================================================================
# Contamination risk (calculations.contamination_risk_score)
# =============================================================================

def contamination_risk_score(equipment, new_product):
    """Integer score 0..100 from the equipment's last product versus the
    incoming lading product, per the facility's contamination policy."""
    last_id = equipment.get("last_product_id")
    if last_id is None:
        return 0
    prev = STORE.products.get(last_id)
    if prev is None:
        return 0
    group_mismatch = 1 if prev["segregation_group"] != new_product["segregation_group"] else 0
    hazard_escalation = 1 if (
        (prev["hazard_class"] == "HAZARDOUS") != (new_product["hazard_class"] == "HAZARDOUS")
    ) else 0
    food_involved = 1 if (
        prev["hazard_class"] == "FOOD_GRADE" or new_product["hazard_class"] == "FOOD_GRADE"
    ) else 0
    if facility_config()["contamination_policy"] == "STRICT_MATRIX":
        return 100 if group_mismatch else 0
    return 60 * group_mismatch + 25 * hazard_escalation + 15 * food_involved


# =============================================================================
# Charges (calculations.cleaning_fee / switching_fee / invoice support)
# =============================================================================

def make_charge(customer_id, railcar_id, charge_type, quantity, amount_cents):
    """Line-level rounding happened upstream; unit_rate_cents is the effective
    blended rate amount/quantity (zero when quantity is zero)."""
    if quantity > 0:
        unit = rhu_cents(Decimal(amount_cents) / Decimal(quantity))
    else:
        unit = 0
    return new_entity(STORE.charges, {
        "customer_id": customer_id,
        "railcar_id": railcar_id,
        "invoice_id": None,
        "charge_type": charge_type,
        "quantity": quantity,
        "unit_rate_cents": unit,
        "amount_cents": amount_cents,
        "status": "ACCRUED",
    })


def create_switch_move(customer_id, track_id, railcar_id, move_type, window_start, window_end):
    """Create a SwitchOrder plus its ACCRUED SWITCHING ChargeEntry.

    Evaluation order is pinned: count the customer's existing switch orders
    (any status) in the UTC calendar month of window_start; sequence_number is
    that count plus one; the move never counts toward its own prior count."""
    free = facility_config()["free_switches_per_period"]
    prior = sum(
        1
        for sw in STORE.switch_orders.values()
        if sw["customer_id"] == customer_id
        and same_utc_month(parse_datetime(sw["window_start"]), window_start)
    )
    seq = prior + 1
    if seq <= free:
        fee = 0
    else:
        fee = BASE_SPOT_FEE if move_type == "SPOT" else BASE_PULL_FEE
    sw = new_entity(STORE.switch_orders, {
        "track_id": track_id,
        "move_type": move_type,
        "railcar_id": railcar_id,
        "customer_id": customer_id,
        "window_start": iso(window_start),
        "window_end": iso(window_end),
        "sequence_number": seq,
        "fee_cents": fee,
        "status": "SCHEDULED",
    }, common=False)
    charge = make_charge(customer_id, railcar_id, "SWITCHING", 1, fee)
    charge["_switch_order_id"] = sw["id"]
    return sw


def void_switch_charge(switch_order_id):
    """Compensation: void the ACCRUED switching charge of a cancelled move."""
    for charge in STORE.charges.values():
        if charge.get("_switch_order_id") == switch_order_id and charge["status"] == "ACCRUED":
            charge["status"] = "VOIDED"
            touch(charge)


# =============================================================================
# Track-space accounting
# =============================================================================

def customer_spot_usage(customer_id):
    """(occupied, reserved): occupied = cars physically holding spots
    (SPOTTED through READY_FOR_RELEASE); reserved = open spot orders."""
    occupied = sum(
        1
        for c in STORE.railcars.values()
        if c["customer_id"] == customer_id and c["placement_status"] in OCCUPIED_PLACEMENTS
    )
    reserved = sum(
        1
        for so in STORE.spot_orders.values()
        if so["status"] in ("REQUESTED", "SCHEDULED")
        and STORE.railcars[so["railcar_id"]]["customer_id"] == customer_id
    )
    return occupied, reserved


def scheduled_count_on_track(track_id):
    return sum(
        1
        for so in STORE.spot_orders.values()
        if so["track_id"] == track_id and so["status"] == "SCHEDULED"
    )


# =============================================================================
# Transfer-order lifecycle helpers
# =============================================================================

def car_empty_cascade(car):
    """IN_TRANSFER car whose remaining quantity reached exactly zero advances
    to EMPTY_AWAITING_CLEANING, and straight on to READY_FOR_RELEASE at the
    same instant when the product does not require a full clean."""
    if car["placement_status"] != "IN_TRANSFER":
        return
    if dec(car["quantity_remaining_tons"]) != 0:
        return
    car["placement_status"] = "EMPTY_AWAITING_CLEANING"
    touch(car)
    product = STORE.products[car["product_id"]]
    if not product["requires_full_clean"]:
        car["placement_status"] = "READY_FOR_RELEASE"
        touch(car)


def complete_transfer_order(order, release_equipment):
    """Shared completion side effects: equipment release when the order was
    ACTIVE; railcar returns to SPOTTED with product remaining, else advances
    toward EMPTY_AWAITING_CLEANING / READY_FOR_RELEASE."""
    if release_equipment:
        eq = STORE.equipment[order["equipment_id"]]
        if eq["status"] == "IN_USE":
            eq["status"] = "AVAILABLE"
            touch(eq)
    car = STORE.railcars[order["railcar_id"]]
    if car["placement_status"] == "IN_TRANSFER":
        if dec(car["quantity_remaining_tons"]) > 0:
            car["placement_status"] = "SPOTTED"
            touch(car)
        else:
            car_empty_cascade(car)
    order["status"] = "COMPLETED"
    touch(order)


# =============================================================================
# Serializers (computed fields reconciled at read time)
# =============================================================================

def car_view(car):
    days, cents = demurrage_accrual(car)
    view = public(car)
    view["demurrage_billable_days"] = days
    view["demurrage_accrued_cents"] = cents
    return view


def lot_view(lot):
    days, cents = sit_accrual(lot)
    view = public(lot)
    view["quantity_on_hand_tons"] = tons_sub(
        tons_sub(lot["quantity_received_tons"], lot["quantity_shipped_tons"]),
        lot["quantity_rejected_tons"],
    )
    view["sit_billable_days"] = days
    view["sit_accrued_cents"] = cents
    return view


def lot_on_hand(lot):
    return tons_sub(
        tons_sub(lot["quantity_received_tons"], lot["quantity_shipped_tons"]),
        lot["quantity_rejected_tons"],
    )
