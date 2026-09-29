"""Calculation rules (PRD 2.6, 3.1-3.11 / SCAFFOLD 1.3).

Every monetary figure is a whole number of cents. Every basis-point product is
divided by 10000 and rounded half up. Generator hours are Decimals carried to
one decimal place and ceiled to the next tenth before pricing.
"""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from store import (add_months, at_time, clock_date, creation_order, db, now,
                   parse_date, parse_dt)

# ------------------------------------------------------------------ constants --
SEASON_DEFAULT_MULTIPLIER_BP = 10000
TOWING_SURCHARGE_BP = 2500
PREMIUM_CEILING_CAP_BP = 1500
LOYALTY_TIER_1_MIN_CENTS = 100000
LOYALTY_TIER_1_BP = 400
LOYALTY_TIER_2_MIN_CENTS = 150000
LOYALTY_TIER_2_BP = 700
SERVICE_FEE_BP = 1200
SCHEDULED_PICKUP_TIME_UTC = (15, 0, 0)
SCHEDULED_RETURN_TIME_UTC = (11, 0, 0)
LATE_GRACE_MINUTES = 60
LATE_HOUR_FEE_CENTS = 7500
LATE_FEE_CAP_BP = 20000
RECORD_LOOKBACK_MONTHS = 36
MAX_RECORD_POINTS = 6
MAX_INFO_ROUNDS = 2
MIN_INSPECTION_PHOTO_ZONES = 5
MIN_TRIP_PHOTO_ZONES = 4
TOWING_ADVANCED_GVWR_THRESHOLD_LBS = 10000
TURNAROUND_BUFFER_NIGHTS = 1
OWNER_SUSPENSION_POINT_THRESHOLD = 12
RENTER_BLOCK_POINT_THRESHOLD = 8
GUIDANCE_WINDOW_DAYS = 90
GUIDANCE_LOOKAHEAD_DAYS = 30
VERDICT_FACTOR_BP = {
    "NEW_DAMAGE": 10000,
    "NO_VISIBLE_CHANGE": 5000,
    "PRE_EXISTING": 0,
}

_ONE = Decimal("1")
_TENTH = Decimal("0.1")


# -------------------------------------------------------------- primitives ----
def rhu(numerator, denominator=1):
    """Round half up (away from zero) to a whole number."""
    value = Decimal(numerator) / Decimal(denominator)
    return int(value.quantize(_ONE, rounding=ROUND_HALF_UP))


def bp_of(amount, basis_points):
    return rhu(Decimal(amount) * Decimal(basis_points), 10000)


def ceil_tenth(hours):
    value = Decimal(hours)
    if value <= 0:
        return Decimal("0.0")
    return value.quantize(_TENTH, rounding=ROUND_CEILING)


def dec(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


# ---------------------------------------------------------- seasonal window ---
def season_for_date(day):
    """(multiplier_bp, season_code) for a calendar date — SCAFFOLD 1.3."""
    month_day = "%02d-%02d" % (day.month, day.day)
    candidates = [s for s in db.pricing_seasons.values()
                  if s["start_month_day"] <= month_day <= s["end_month_day"]]
    if not candidates:
        return SEASON_DEFAULT_MULTIPLIER_BP, "OFF"
    winner = creation_order(candidates)[0]
    return winner["multiplier_bp"], winner["season_code"]


# ------------------------------------------------------- booking components ---
def booking_nightly_subtotal(listing, start_date, nights):
    """Round per night, then sum. Never sum then round."""
    total = 0
    for offset in range(nights):
        day = start_date + timedelta(days=offset)
        multiplier_bp, _ = season_for_date(day)
        total += bp_of(listing["base_nightly_rate_cents"], multiplier_bp)
    return total


def protection_premium(listing, plan, nights, base_subtotal_cents, frozen_tier):
    tier_premium = max(
        plan["daily_premium_cents"] * nights,
        bp_of(base_subtotal_cents, plan["premium_pct_of_base_bp"]),
    )
    if listing["requires_towing"] and frozen_tier == "BASIC":
        surcharge = bp_of(tier_premium, TOWING_SURCHARGE_BP)
    else:
        surcharge = 0
    ceiling = bp_of(plan["coverage_ceiling_cents"], PREMIUM_CEILING_CAP_BP)
    return min(tier_premium + surcharge, ceiling)


def delivery_fee(listing, distance_miles, setup_fee_cents):
    return (listing["delivery_base_fee_cents"]
            + listing["delivery_per_mile_cents"] * distance_miles
            + setup_fee_cents)


def loyalty_for(pre_discount_cents):
    if pre_discount_cents >= LOYALTY_TIER_2_MIN_CENTS:
        return "LOYALTY_TIER_2", LOYALTY_TIER_2_BP
    if pre_discount_cents >= LOYALTY_TIER_1_MIN_CENTS:
        return "LOYALTY_TIER_1", LOYALTY_TIER_1_BP
    return "NONE", 0


def pooled_overage(listing, nights, miles_used, generator_used):
    """The TRIP_TOTAL shape, shared by the reporting figure and the estimate."""
    miles_allowance = nights * listing["included_miles_per_night"]
    total = max(0, miles_used - miles_allowance) * listing["mileage_overage_rate_cents_per_mile"]
    gen_allowance = dec(nights) * dec(listing["included_generator_hours_per_night"])
    billable = ceil_tenth(dec(generator_used) - gen_allowance)
    total += rhu(billable * Decimal(listing["generator_overage_rate_cents_per_hour"]))
    return total


def estimated_overage(listing, nights, declared_miles, declared_generator_hours):
    return pooled_overage(listing, nights, declared_miles, declared_generator_hours)


def quote_total(booking, listing):
    """The six pinned steps of PRD 3.5. Mutates the booking's quote fields."""
    pre_discount = (booking["base_subtotal_cents"]
                    + booking["premium_cents"]
                    + booking["delivery_fee_cents"])
    tier, tier_bp = loyalty_for(pre_discount)
    discount = bp_of(pre_discount, tier_bp)
    discounted = pre_discount - discount
    service_fee = bp_of(discounted, SERVICE_FEE_BP)
    estimated = estimated_overage(listing, booking["nights"],
                                 booking["declared_miles"],
                                 booking["declared_generator_hours"])
    booking["loyalty_tier"] = tier
    booking["loyalty_discount_cents"] = discount
    booking["service_fee_cents"] = service_fee
    booking["estimated_overage_cents"] = estimated
    booking["quoted_total_cents"] = discounted + service_fee + estimated


# --------------------------------------------------------- metered overages ---
def sorted_readings(booking_id):
    rows = [r for r in db.meter_readings.values() if r["booking_id"] == booking_id]
    return sorted(rows, key=lambda r: (r["_recorded_at"], r["created_at"], r["_seq"]))


def segment_wise_overage(listing, readings):
    total = 0
    for earlier, later in zip(readings, readings[1:]):
        nights = (later["_recorded_at"].date() - earlier["_recorded_at"].date()).days
        if nights == 0:
            nights = 1
        miles_allowance = nights * listing["included_miles_per_night"]
        miles_used = later["odometer_miles"] - earlier["odometer_miles"]
        total += max(0, miles_used - miles_allowance) * listing["mileage_overage_rate_cents_per_mile"]
        gen_allowance = dec(nights) * dec(listing["included_generator_hours_per_night"])
        gen_used = dec(later["generator_hours"]) - dec(earlier["generator_hours"])
        billable = ceil_tenth(gen_used - gen_allowance)
        total += rhu(billable * Decimal(listing["generator_overage_rate_cents_per_hour"]))
    return total


def trip_total_overage(listing, booking, readings):
    pre = [r for r in readings if r["reading_type"] == "PRE_TRIP"]
    post = [r for r in readings if r["reading_type"] == "POST_TRIP"]
    if not pre or not post:
        return 0
    first = pre[0]
    last = post[-1]
    miles_used = last["odometer_miles"] - first["odometer_miles"]
    gen_used = dec(last["generator_hours"]) - dec(first["generator_hours"])
    return pooled_overage(listing, booking["nights"], miles_used, gen_used)


# --------------------------------------------------------------- lateness -----
def late_return_fee(listing, booking):
    scheduled = at_time(parse_date(booking["end_date"]), *SCHEDULED_RETURN_TIME_UTC)
    late_minutes = max(0, math.floor((now() - scheduled).total_seconds() / 60))
    if late_minutes <= LATE_GRACE_MINUTES:
        return 0
    blocks = math.ceil((late_minutes - LATE_GRACE_MINUTES) / 60)
    cap = bp_of(listing["base_nightly_rate_cents"], LATE_FEE_CAP_BP)
    return min(blocks * LATE_HOUR_FEE_CENTS, cap)


# ------------------------------------------------------------ final totals ----
def damage_renter_charge(booking_id):
    return sum(c["renter_charge_cents"] for c in db.damage_claims.values()
               if c["booking_id"] == booking_id and c["status"] in ("APPROVED", "PARTIAL"))


def final_trip_total(booking):
    discounted = (booking["base_subtotal_cents"] + booking["premium_cents"]
                  + booking["delivery_fee_cents"] - booking["loyalty_discount_cents"])
    booking["final_total_cents"] = (discounted
                                    + booking["service_fee_cents"]
                                    + booking["final_overage_cents"]
                                    + booking["late_return_fee_cents"]
                                    + damage_renter_charge(booking["id"]))
    booking["balance_due_cents"] = booking["final_total_cents"] - booking["hold_amount_cents"]


# ------------------------------------------------------------- cancellation ---
def hours_before_pickup(booking):
    pickup = at_time(parse_date(booking["start_date"]), *SCHEDULED_PICKUP_TIME_UTC)
    return math.floor((pickup - now()).total_seconds() / 3600)


# ------------------------------------------------- renter risk / credentials ---
def driving_record_rows(renter_id):
    return [q for q in db.renter_qualifications.values()
            if q["renter_id"] == renter_id and q["check_type"] == "DRIVING_RECORD"]


def newest_driving_record(renter_id):
    rows = driving_record_rows(renter_id)
    if not rows:
        return None
    return sorted(rows, key=lambda r: (r["_checked_at"], r["created_at"], r["_seq"]),
                  reverse=True)[0]


def rolling_record_points(renter_id):
    window_start = add_months(now(), -RECORD_LOOKBACK_MONTHS)
    total = 0
    for row in driving_record_rows(renter_id):
        if window_start <= row["_checked_at"] <= now():
            total += row["violation_points"]
    return total


def towing_tier(renter_id, as_of_date):
    """Highest tier among unexpired TOWING_EXPERIENCE checks; ADVANCED > BASIC."""
    tier = "NONE"
    for row in db.renter_qualifications.values():
        if row["renter_id"] != renter_id or row["check_type"] != "TOWING_EXPERIENCE":
            continue
        if parse_date(row["expires_on"]) < as_of_date:
            continue
        if row["result"] == "VERIFIED_ADVANCED":
            return "ADVANCED"
        if row["result"] == "VERIFIED_BASIC":
            tier = "BASIC"
    return tier


def recompute_renter_qualification(renter):
    renter["driving_record_points"] = rolling_record_points(renter["id"])
    newest = newest_driving_record(renter["id"])
    if newest is None:
        renter["driving_record_status"] = "NONE"
    elif parse_date(newest["expires_on"]) < clock_date():
        renter["driving_record_status"] = "EXPIRED"
    else:
        renter["driving_record_status"] = newest["result"]
    renter["towing_verified_tier"] = towing_tier(renter["id"], clock_date())


def age_years(date_of_birth, on_date):
    born = parse_date(date_of_birth)
    years = on_date.year - born.year
    if (on_date.month, on_date.day) < (born.month, born.day):
        years -= 1
    return years


# ------------------------------------------------------------ damage claims ---
def photo_comparison(booking_id, zone):
    pre = [p for p in db.trip_photos.values()
           if p["booking_id"] == booking_id and p["phase"] == "PRE_TRIP" and p["zone"] == zone]
    post = [p for p in db.trip_photos.values()
            if p["booking_id"] == booking_id and p["phase"] == "POST_TRIP" and p["zone"] == zone]
    if any(p["damage_flagged"] for p in pre):
        verdict = "PRE_EXISTING"
    elif any(p["damage_flagged"] for p in post):
        verdict = "NEW_DAMAGE"
    else:
        verdict = "NO_VISIBLE_CHANGE"
    return len(pre), len(post), verdict


def adjudicate_amounts(claim, plan, override_amount_cents):
    if claim["cause_code"] in plan["excluded_causes"]:
        gross = 0
    elif override_amount_cents is not None:
        gross = min(override_amount_cents, plan["coverage_ceiling_cents"])
    else:
        eligible = min(claim["claimed_amount_cents"], plan["coverage_ceiling_cents"])
        gross = bp_of(eligible, VERDICT_FACTOR_BP[claim["comparison_verdict"]])
    renter_charge = min(gross, plan["deductible_cents"])
    plan_paid = gross - renter_charge
    if gross == 0:
        status = "DENIED"
    elif gross >= claim["claimed_amount_cents"]:
        status = "APPROVED"
    else:
        status = "PARTIAL"
    return gross, renter_charge, plan_paid, gross, status


# -------------------------------------------------------- pricing guidance ----
def pricing_guidance(listing):
    window_start = clock_date()
    window_end = window_start + timedelta(days=GUIDANCE_WINDOW_DAYS - 1)
    covered = set()
    for booking in db.bookings.values():
        if booking["listing_id"] != listing["id"]:
            continue
        if booking["trip_status"] not in ("CONFIRMED", "IN_TRIP", "RETURNED", "CLOSED"):
            continue
        day = parse_date(booking["start_date"])
        end = parse_date(booking["end_date"])
        while day < end:
            if window_start <= day <= window_end:
                covered.add(day)
            day += timedelta(days=1)
    booked_nights = len(covered)
    utilization_bp = rhu(booked_nights * 10000, GUIDANCE_WINDOW_DAYS)
    if utilization_bp >= 7000:
        util_adj_bp = 1500
    elif utilization_bp >= 4000:
        util_adj_bp = 500
    elif utilization_bp >= 2000:
        util_adj_bp = 0
    else:
        util_adj_bp = -1000
    season_mult_bp, season_code = season_for_date(
        window_start + timedelta(days=GUIDANCE_LOOKAHEAD_DAYS))
    suggested = rhu(
        Decimal(listing["base_nightly_rate_cents"])
        * Decimal(10000 + util_adj_bp) * Decimal(season_mult_bp),
        100000000)
    return {
        "listing_id": listing["id"],
        "window_start_date": window_start.isoformat(),
        "window_end_date": window_end.isoformat(),
        "booked_nights": booked_nights,
        "utilization_bp": utilization_bp,
        "util_adj_bp": util_adj_bp,
        "season_code": season_code,
        "season_multiplier_bp": season_mult_bp,
        "suggested_nightly_rate_cents": suggested,
    }
