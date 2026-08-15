"""Business logic: derived capacity counters (PRD 2.6), calculations
(scaffold table 3), and the cascade side effects (state machine table).

All monetary / weight arithmetic uses Decimal(str(x)) so that the pinned
round-half-up contract (PRD 2.9) is honored exactly -- never binary floats.
"""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from timeutil import parse_instant


# ---------------------------------------------------------------------------
# Constants (scaffold calculations table)
# ---------------------------------------------------------------------------

VOLUMETRIC_FACTOR = Decimal("167.0")     # kg per m3 (IATA 1:6000)
FREE_DAYS = 3
TIER1_DAYS = 4
TIER1_RATE = Decimal("50.00")            # per ULD per day
TIER2_RATE = Decimal("120.00")           # per ULD per day
LIABILITY_RATE_PER_KG = Decimal("19.00")

ALLOCATED_STATUSES = ("ACCEPTED", "BUILT_UP")
OPEN_PLAN_STATUSES = ("DRAFT", "SEALED")

BUILD_WINDOW_BUFFER = timedelta(minutes=30)


def dec(value) -> Decimal:
    """Decimal from a JSON number via its shortest string form, so that
    0.335 is exactly Decimal('0.335') (not the binary-float expansion)."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def money2(value: Decimal) -> float:
    return float(round2(value))


def num(value: Decimal) -> float:
    return float(value)


# ---------------------------------------------------------------------------
# Derived counters (PRD 2.6: "the server derives from its dependent
# resources"; always computed from source rows, never stored incrementally)
# ---------------------------------------------------------------------------

def bookings_on_flight(flight_id: str) -> list:
    return [b for b in db.bookings.values() if b["flight_id"] == flight_id]


def allocated_weight_kg(flight_id: str) -> Decimal:
    return sum(
        (dec(b["gross_weight_kg"]) for b in bookings_on_flight(flight_id)
         if b["status"] in ALLOCATED_STATUSES),
        Decimal(0),
    )


def allocated_volume_m3(flight_id: str) -> Decimal:
    return sum(
        (dec(b["volume_m3"]) for b in bookings_on_flight(flight_id)
         if b["status"] in ALLOCATED_STATUSES),
        Decimal(0),
    )


def reserved_positions(flight_id: str) -> int:
    return sum(
        1 for p in db.build_up_plans.values()
        if p["flight_id"] == flight_id and p["status"] in OPEN_PLAN_STATUSES
    )


def bookings_on_plan(plan_id: str) -> list:
    """Bookings currently BUILT_UP on the plan."""
    return [
        b for b in db.bookings.values()
        if b.get("build_up_plan_id") == plan_id and b["status"] == "BUILT_UP"
    ]


def plan_total_weight_kg(plan_id: str) -> Decimal:
    return sum((dec(b["gross_weight_kg"]) for b in bookings_on_plan(plan_id)), Decimal(0))


def active_hold_for_booking(booking_id: str):
    for h in db.customs_holds.values():
        if h["booking_id"] == booking_id and h["status"] == "ACTIVE":
            return h
    return None


def pending_declaration_for_booking(booking_id: str):
    for d in db.dg_declarations.values():
        if d["booking_id"] == booking_id and d["status"] == "PENDING_CHECK":
            return d
    return None


def accepted_declaration_for_booking(booking_id: str):
    for d in db.dg_declarations.values():
        if d["booking_id"] == booking_id and d["status"] == "ACCEPTED":
            return d
    return None


def provisional_charge(uld_id: str, charge_type: str):
    """The current PROVISIONAL charge of a type for a unit (latest first)."""
    rows = [
        c for c in db.uld_charges.values()
        if c["uld_id"] == uld_id and c["charge_type"] == charge_type
        and c["status"] == "PROVISIONAL"
    ]
    rows.sort(key=lambda c: c["_seq"], reverse=True)
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Calculations (scaffold table 3)
# ---------------------------------------------------------------------------

def chargeable_weight_kg(gross_weight, volume) -> float:
    """max(gross, volume * 167.0), rounded half-up to 2dp; computed once."""
    return money2(max(dec(gross_weight), dec(volume) * VOLUMETRIC_FACTOR))


def demurrage(dispatched_at: str, end_ts: str):
    """Tiered demurrage. Returns (amount: float, tier1_days, tier2_days).

    days_in_use    = floor((end - dispatched_at) / 86400)   # whole 24h periods
    chargeable     = max(0, days_in_use - FREE_DAYS)
    tier1_days     = min(chargeable, TIER1_DAYS)
    tier2_days     = chargeable - tier1_days
    amount         = round_half_up(tier1 * 50.00 + tier2 * 120.00, 2)
    """
    start = parse_instant(dispatched_at)
    end = parse_instant(end_ts)
    seconds = (end - start).total_seconds()
    days_in_use = math.floor(seconds / 86400)
    chargeable_days = max(0, days_in_use - FREE_DAYS)
    tier1_days = min(chargeable_days, TIER1_DAYS)
    tier2_days = chargeable_days - tier1_days
    amount = money2(Decimal(tier1_days) * TIER1_RATE + Decimal(tier2_days) * TIER2_RATE)
    return amount, tier1_days, tier2_days


def claim_settlement(claim: dict, booking: dict):
    """Returns (item_total: float, basis: str, approved_amount: float).

    PINNED ROUNDING ORDER: each per-item term is rounded half-up to 2dp
    FIRST, then the rounded terms are summed.
    """
    item_total = sum(
        (round2(dec(item["weight_kg"]) * LIABILITY_RATE_PER_KG) for item in claim["items"]),
        Decimal(0),
    )
    if booking.get("declared_value") is None:
        basis = "LIABILITY"
        cap = round2(dec(booking["chargeable_weight_kg"]) * LIABILITY_RATE_PER_KG)
    else:
        basis = "DECLARED_VALUE"
        cap = dec(booking["declared_value"])
    approved = round2(min(dec(claim["claimed_amount"]), item_total, cap))
    return float(item_total), basis, float(approved)


# ---------------------------------------------------------------------------
# Build-window separation (validation rung 11): on the same flight, the new
# window must end at least 30 minutes before, or begin at least 30 minutes
# after, every DRAFT/SEALED plan's window; exactly 30 minutes is permitted.
# ---------------------------------------------------------------------------

def build_window_conflict(flight_id: str, build_start: str, build_end: str) -> bool:
    new_start = parse_instant(build_start)
    new_end = parse_instant(build_end)
    for plan in db.build_up_plans.values():
        if plan["flight_id"] != flight_id or plan["status"] not in OPEN_PLAN_STATUSES:
            continue
        other_start = parse_instant(plan["build_start"])
        other_end = parse_instant(plan["build_end"])
        separated = (new_end + BUILD_WINDOW_BUFFER <= other_start) or (
            new_start >= other_end + BUILD_WINDOW_BUFFER
        )
        if not separated:
            return True
    return False


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def offload_booking(booking: dict, flight: dict) -> None:
    """Booking -> OFFLOADED with the full BUILT_UP cascade (PRD 3.7):

    release flight allocation (derived; flight version bump), remove from the
    plan (plan bump), auto-cancel an emptied DRAFT plan (plan bump), release
    its ULD ASSIGNED -> SERVICEABLE (uld bump).
    """
    if booking["status"] == "BUILT_UP":
        plan = db.build_up_plans.get(booking.get("build_up_plan_id"))
        booking["build_up_plan_id"] = None
        if plan is not None:
            db.touch(plan)  # plan.total_weight_kg (derived) decreased
            if plan["status"] == "DRAFT" and len(bookings_on_plan(plan["id"])) == 0:
                plan["status"] = "CANCELLED"
                db.touch(plan)
                db.touch(flight)  # reserved_positions (derived) decremented
                uld = db.ulds.get(plan["uld_id"])
                if uld is not None and uld["status"] == "ASSIGNED":
                    uld["status"] = "SERVICEABLE"
                    db.touch(uld)
    booking["status"] = "OFFLOADED"
    db.touch(booking)
    db.touch(flight)  # allocated_weight_kg / allocated_volume_m3 released


def depart_flight(flight: dict) -> None:
    """The five-link departure cascade (PRD 3.8)."""
    now = db.now_iso()
    sealed = [
        p for p in db.build_up_plans.values()
        if p["flight_id"] == flight["id"] and p["status"] == "SEALED"
    ]
    sealed.sort(key=lambda p: p["_seq"])
    for plan in sealed:
        # link 1: plan SEALED -> DEPARTED
        plan["status"] = "DEPARTED"
        db.touch(plan)
        # link 2: the plan's ULD ASSIGNED -> DISPATCHED
        uld = db.ulds.get(plan["uld_id"])
        if uld is not None and uld["status"] == "ASSIGNED":
            uld["status"] = "DISPATCHED"
            uld["dispatched_at"] = now
            db.touch(uld)
            # link 3: PROVISIONAL DEMURRAGE charge (end = scheduled_arrival)
            amount, tier1_days, tier2_days = demurrage(
                uld["dispatched_at"], flight["scheduled_arrival"]
            )
            charge = {
                "uld_id": uld["id"],
                "charge_type": "DEMURRAGE",
                "amount": amount,
                "tier1_days": tier1_days,
                "tier2_days": tier2_days,
                "description": None,
                "status": "PROVISIONAL",
            }
            db.stamp_new(charge)
            db.uld_charges[charge["id"]] = charge
        # link 4: every BUILT_UP booking on the departed plan -> LOADED
        for booking in bookings_on_plan(plan["id"]):
            booking["status"] = "LOADED"
            booking["build_up_plan_id"] = None
            db.touch(booking)
    # link 5: every ACCEPTED booking never built -> OFFLOADED (missed departure)
    for booking in bookings_on_flight(flight["id"]):
        if booking["status"] == "ACCEPTED":
            booking["status"] = "OFFLOADED"
            db.touch(booking)
            db.touch(flight)  # allocation released
    flight["status"] = "DEPARTED"
    db.touch(flight)


def finalize_demurrage(uld: dict) -> None:
    """ULD DISPATCHED -> RETURNED: recompute the PROVISIONAL DEMURRAGE charge
    with end = returned_at and move it to FINALIZED (final variant)."""
    charge = provisional_charge(uld["id"], "DEMURRAGE")
    if charge is None:
        return
    amount, tier1_days, tier2_days = demurrage(uld["dispatched_at"], uld["returned_at"])
    charge["amount"] = amount
    charge["tier1_days"] = tier1_days
    charge["tier2_days"] = tier2_days
    charge["status"] = "FINALIZED"
    db.touch(charge)
