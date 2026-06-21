"""Calculation rules (SCAFFOLD §1.3, PRD §3.3–§3.8). All money in whole cents;
fractional results rounded half up. decimal.Decimal is used wherever a
multiplier / discount / fraction can produce a fractional cent.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

import db

DEFAULT_MULTIPLIER_BP = 10000
TURNAROUND_MINUTES = 30
BUNDLE_DISCOUNT_RATE = Decimal("0.95")
BUNDLE_MIN_PACKAGES = 2
DAMAGE_FRACTION = Decimal("0.40")

# customer_standing constants
LATE_STRIKE = 1
DAMAGE_STRIKE = 2
LOSS_STRIKE = 4
WATCH_AT = 2
SUSPEND_AT = 4

# severity ladder
SEVERITY = {"GOOD": 0, "WORN": 1, "DAMAGED": 2, "LOST": 3}


def round_half_up(value):
    """Round a Decimal (or numeric) to the nearest whole cent, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def minutes_between(start, end):
    return (end - start).total_seconds() / 60.0


def ceil_div_minutes(start, end, per):
    """ceil( minutes(start,end) / per ), as a started-unit count."""
    mins = minutes_between(start, end)
    return int(math.ceil(mins / per))


def season_multiplier_bp(category, instant):
    """demand_multiplier_bp of the SeasonWindow whose half-open
    [starts_on, ends_on) contains `instant` and whose category matches;
    DEFAULT_MULTIPLIER_BP if none."""
    for s in db.season_windows.values():
        if s["category"] != category:
            continue
        if s["starts_on"] <= instant < s["ends_on"]:
            return s["demand_multiplier_bp"]
    return DEFAULT_MULTIPLIER_BP


def tiered_rental(rate_card, category, window_start, window_end, multiplier_instant, damage_waiver_opted):
    """Core tiered pricing shared by quote (requested window) and final
    settlement (actual window). Returns (rental_cents, waiver_cents, basis)."""
    span_hours = ceil_div_minutes(window_start, window_end, 60)
    span_days = ceil_div_minutes(window_start, window_end, 1440)
    mult_bp = season_multiplier_bp(category, multiplier_instant)

    base_hourly = rate_card["hourly_cents"] * span_hours
    base_daily = rate_card["daily_cents"] * span_days
    base_seasonal = rate_card["seasonal_flat_cents"]

    # cheapest base; tie-break HOURLY < DAILY < SEASONAL.
    chosen_base = base_hourly
    basis = "HOURLY"
    if base_daily < chosen_base:
        chosen_base = base_daily
        basis = "DAILY"
    if base_seasonal < chosen_base:
        chosen_base = base_seasonal
        basis = "SEASONAL"

    # multiplier applied to chosen_base BEFORE rounding.
    rental_cents = round_half_up(Decimal(chosen_base) * Decimal(mult_bp) / Decimal(10000))

    waiver_cents = 0
    if damage_waiver_opted:
        waiver_cents = rate_card["damage_waiver_cents_per_day"] * span_days

    return rental_cents, waiver_cents, basis


def addons_total(reservation_id):
    """Add-ons subtotal: round each line's post-discount price half up FIRST,
    then sum. 5% bundle discount when >= 2 PACKAGE lines on the reservation."""
    lines = [ra for ra in db.reservation_addons.values()
             if ra["reservation_id"] == reservation_id]
    package_count = 0
    for ra in lines:
        ad = db.addons.get(ra["addon_id"])
        if ad and ad["kind"] == "PACKAGE":
            package_count += 1
    bundle = package_count >= BUNDLE_MIN_PACKAGES

    total = 0
    for ra in lines:
        price = Decimal(ra["price_cents"])
        if bundle:
            price = price * BUNDLE_DISCOUNT_RATE
        total += round_half_up(price)
    return total


def quote_rental_cost(reservation, rate_card, gear_type):
    """Provisional quote on the requested window [pickup_at, due_at).
    Returns (quoted_total_cents, quoted_rate_basis)."""
    rental_cents, waiver_cents, basis = tiered_rental(
        rate_card,
        gear_type["category"],
        reservation["pickup_at"],
        reservation["due_at"],
        reservation["pickup_at"],
        reservation["damage_waiver_opted"],
    )
    total = rental_cents + waiver_cents + addons_total(reservation["id"])
    return total, basis


def late_fee(reservation, rate_card):
    """late_fee_cents per RateCard. grace deadline = due_at + grace_minutes;
    <= deadline is on time (inclusive)."""
    from datetime import timedelta
    grace_end = reservation["due_at"] + timedelta(minutes=rate_card["grace_minutes"])
    returned_at = reservation["returned_at"]
    if returned_at <= grace_end:
        return 0
    late_hours = ceil_div_minutes(grace_end, returned_at, 60)
    return rate_card["late_fee_cents_per_hour"] * late_hours


def damage_charge(checkout_rating, checkin_rating, damage_waiver_opted, loss_fee_cents):
    """Returns (outcome, charge_cents, waiver_applied)."""
    checkout_sev = SEVERITY[checkout_rating] if checkout_rating in SEVERITY else 0
    checkin_sev = SEVERITY[checkin_rating]
    if checkin_sev == SEVERITY["LOST"]:
        return "LOSS", loss_fee_cents, False
    if checkin_sev > checkout_sev and checkin_sev == SEVERITY["DAMAGED"]:
        if damage_waiver_opted:
            return "DAMAGE", 0, True
        charge = round_half_up(Decimal(loss_fee_cents) * DAMAGE_FRACTION)
        return "DAMAGE", charge, False
    return "NONE", 0, False


def final_settlement(reservation, rate_card, gear_type, late_fee_cents, damage_charge_cents):
    """Final total on ACTUAL usage [picked_up_at, returned_at), multiplier from
    season covering picked_up_at. Returns (final_total_cents, rental_basis)."""
    rental_cents, waiver_cents, basis = tiered_rental(
        rate_card,
        gear_type["category"],
        reservation["picked_up_at"],
        reservation["returned_at"],
        reservation["picked_up_at"],
        reservation["damage_waiver_opted"],
    )
    final_total = (rental_cents + waiver_cents + addons_total(reservation["id"])
                   + late_fee_cents + damage_charge_cents)
    return final_total, rental_cents, basis


def window_overlap(gear_unit_id, new_pickup, new_due, exclude_reservation_id=None):
    """True when [new_pickup, new_due) collides with any non-terminal
    reservation on the same unit, after adding TURNAROUND_MINUTES buffer to
    each existing window's end."""
    from datetime import timedelta
    for r in db.reservations.values():
        if r["gear_unit_id"] != gear_unit_id:
            continue
        if exclude_reservation_id and r["id"] == exclude_reservation_id:
            continue
        if r["lifecycle_status"] not in ("QUOTED", "CONFIRMED", "PICKED_UP"):
            continue
        existing_end_buffered = r["due_at"] + timedelta(minutes=TURNAROUND_MINUTES)
        # new.pickup < existing_end_buffered AND existing.pickup < new.due
        if new_pickup < existing_end_buffered and r["pickup_at"] < new_due:
            return True
    return False


def intervals_intersect_closed(a_start, a_end, b_start, b_end):
    """Closed-interval intersection: touching endpoints DO collide."""
    return a_start <= b_end and b_start <= a_end


def recompute_customer_standing(customer):
    """Re-derive strike_points, open_loss_balance_cents, standing for a customer
    across all of their reservations + unsettled LOSS_FEE ledger entries."""
    cust_id = customer["id"]
    strike_points = 0
    for r in db.reservations.values():
        if r["customer_id"] != cust_id:
            continue
        # late return strike
        if r["lifecycle_status"] in ("RETURNED", "CLOSED") and r["late_fee_cents"] and r["late_fee_cents"] > 0:
            strike_points += LATE_STRIKE
        # damage/loss strike from this reservation's assessment
        for da in db.damage_assessments.values():
            if da["reservation_id"] != r["id"]:
                continue
            if da["outcome"] == "DAMAGE":
                strike_points += DAMAGE_STRIKE
            elif da["outcome"] == "LOSS":
                strike_points += LOSS_STRIKE
    if strike_points < 0:
        strike_points = 0

    open_loss = 0
    for le in db.ledger_entries.values():
        if le["customer_id"] == cust_id and le["entry_type"] == "LOSS_FEE" and not le["settled"]:
            open_loss += le["amount_cents"]

    if open_loss > 0 or strike_points >= SUSPEND_AT:
        standing = "SUSPENDED"
    elif strike_points >= WATCH_AT:
        standing = "WATCH"
    else:
        standing = "GOOD"

    customer["strike_points"] = strike_points
    customer["open_loss_balance_cents"] = open_loss
    customer["standing"] = standing
