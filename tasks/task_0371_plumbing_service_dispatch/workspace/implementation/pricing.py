"""Pricing / calculation logic (PRD §2.8, §3.3, §3.6, §3.9).

All monetary amounts are integer cents. Rounding is round-half-up, pinned at
the per-line multiplication and at the discount. Subtotals (sums of already
rounded line totals) are NEVER re-rounded.
"""
from decimal import Decimal, ROUND_HALF_UP

import db

# Constants (scaffold §1.3 / PRD §3).
AFTER_HOURS_MULT = Decimal("1.5")
MAX_DISCOUNT_CENTS = 15000
TRIP_FEE_BASE_CENTS = 8900
TRIP_WAIVE_THRESHOLD_CENTS = 50000
EMERGENCY_SURCHARGE_CENTS = 12000
AFTER_HOURS_CUTOFF_HOUR = 18
TRAVEL_BUFFER_MINUTES = 30
WARRANTY_DAYS = 90
ROLLING_WINDOW = 5


def round_half_up(value):
    """Round a numeric value to the nearest whole integer, half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _plan_for_customer(customer):
    """Return (labor_discount_pct, waives_trip_fee) for a customer's plan.

    A customer with no plan (null membership_plan_id) is treated as tier NONE:
    no discount, no trip-fee waiver.
    """
    plan_id = customer.get("membership_plan_id")
    if not plan_id:
        return Decimal("0"), False
    plan = db.membership_plans.get(plan_id)
    if plan is None:
        return Decimal("0"), False
    pct = Decimal(str(plan["labor_discount_pct"]))
    return pct, bool(plan["waives_trip_fee"])


def after_hours_multiplier(job):
    return AFTER_HOURS_MULT if job.get("after_hours") else Decimal("1.0")


def compute_line_pricing(line, job):
    """Compute (unit_price_cents, line_total_cents) for an estimate line.

    FLAT_RATE: unit = round_half_up(base_price * after_hours_multiplier)
    PART:      unit = list_price_cents (untouched by multiplier/discount)
    line_total = round_half_up(unit_price * quantity)  -- rounded per line.
    """
    quantity = line["quantity"]
    if line["line_type"] == "FLAT_RATE":
        item = db.flat_rate_items[line["flat_rate_item_id"]]
        mult = after_hours_multiplier(job)
        unit = round_half_up(Decimal(item["base_price_cents"]) * mult)
    else:  # PART
        part = db.parts[line["part_id"]]
        unit = part["list_price_cents"]
    line_total = round_half_up(Decimal(unit) * quantity)
    return unit, line_total


def price_estimate(estimate, job, customer):
    """Provisional pricing pass (PRD §3.3). Mutates the estimate's computed
    money fields and each line's unit_price/line_total in place. Returns the
    estimate.
    """
    lines = [l for l in db.estimate_lines.values()
             if l["estimate_id"] == estimate["id"]]

    labor_subtotal = 0
    parts_subtotal = 0
    for line in lines:
        unit, total = compute_line_pricing(line, job)
        line["unit_price_cents"] = unit
        line["line_total_cents"] = total
        db.touch(line)
        if line["line_type"] == "FLAT_RATE":
            labor_subtotal += total
        else:
            parts_subtotal += total

    pct, waives_trip = _plan_for_customer(customer)
    discount = min(round_half_up(Decimal(labor_subtotal) * pct), MAX_DISCOUNT_CENTS)
    labor_after = labor_subtotal - discount

    waive = waives_trip or (labor_after >= TRIP_WAIVE_THRESHOLD_CENTS)
    trip_fee = 0 if waive else TRIP_FEE_BASE_CENTS

    emergency = EMERGENCY_SURCHARGE_CENTS if job["priority"] == "EMERGENCY" else 0

    total = labor_after + parts_subtotal + trip_fee + emergency

    estimate["labor_subtotal_cents"] = labor_subtotal
    estimate["parts_subtotal_cents"] = parts_subtotal
    estimate["discount_cents"] = discount
    estimate["trip_fee_cents"] = trip_fee
    estimate["emergency_surcharge_cents"] = emergency
    estimate["estimate_total_cents"] = total
    return estimate


def compute_invoice_totals(job, customer, consumed_parts):
    """Final pricing at completion (PRD §3.6).

    final_labor_cents: recomputed from the approved estimate's FLAT_RATE lines
      (after-hours mult + membership discount with cap), captured at invoice time.
    final_parts_cents: from ACTUAL consumed parts (list_price * units), summed.
    Trip fee + emergency recomputed with the same constants/rules.

    consumed_parts: list of {"part_id": ..., "units": int} (already validated).
    Returns (final_labor_cents, final_parts_cents, final_total_cents).
    """
    estimate = db.estimates.get(job.get("authorized_estimate_id"))
    flat_lines = []
    if estimate is not None:
        flat_lines = [l for l in db.estimate_lines.values()
                      if l["estimate_id"] == estimate["id"]
                      and l["line_type"] == "FLAT_RATE"]

    labor_subtotal = 0
    for line in flat_lines:
        item = db.flat_rate_items[line["flat_rate_item_id"]]
        mult = after_hours_multiplier(job)
        unit = round_half_up(Decimal(item["base_price_cents"]) * mult)
        labor_subtotal += round_half_up(Decimal(unit) * line["quantity"])

    pct, waives_trip = _plan_for_customer(customer)
    discount = min(round_half_up(Decimal(labor_subtotal) * pct), MAX_DISCOUNT_CENTS)
    labor_after = labor_subtotal - discount

    # Final parts: per distinct consumed part, list_price * units, round per part.
    final_parts = 0
    for cp in consumed_parts:
        part = db.parts[cp["part_id"]]
        final_parts += round_half_up(Decimal(part["list_price_cents"]) * cp["units"])

    waive = waives_trip or (labor_after >= TRIP_WAIVE_THRESHOLD_CENTS)
    trip_fee = 0 if waive else TRIP_FEE_BASE_CENTS

    emergency = EMERGENCY_SURCHARGE_CENTS if job["priority"] == "EMERGENCY" else 0

    final_total = labor_after + final_parts + trip_fee + emergency
    return labor_subtotal, final_parts, final_total


def rate_4dp(numerator, denominator):
    """Return numerator/denominator rounded half-up to 4 decimal places as a
    float; 0.0 when denominator is 0 (PRD §3.9)."""
    if denominator == 0:
        return 0.0
    q = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)
