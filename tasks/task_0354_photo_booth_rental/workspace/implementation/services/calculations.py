"""Calculation rules (SCAFFOLD §1.3 / PRD §3). All money uses Decimal with
ROUND_HALF_UP to exactly two decimal places."""
import math
from decimal import Decimal, ROUND_HALF_UP

# Constants (SCAFFOLD §1.3 / PRD §3)
TRAVEL_FREE_RADIUS_MILES = 25
TRAVEL_RATE_PER_MILE = Decimal("1.50")
OVERTIME_DAILY_CAP = Decimal("750.00")
DEPOSIT_PCT = Decimal("0.25")
TIER_FULL_DAYS = 60
TIER_HALF_DAYS = 30

# Interval buffers (minutes) — PRD §2.6. Numeric values pinned by the §1.8
# interval test recipes: event 18:00-22:00 occupies the booth [16:30, 01:00)
# (setup 90 min back, teardown 60 + turnaround 120 = 180 min forward) and the
# attendant [16:30, 23:00] (setup 90, teardown 60, NO turnaround).
SETUP_BUFFER_MIN = 90
TEARDOWN_BUFFER_MIN = 60
TURNAROUND_BUFFER_MIN = 120

_CENTS = Decimal("0.01")


def round2(value):
    """Round half-up to two decimal places (PRD §2.5)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def to_number(d):
    """Render a Decimal money value as a JSON number (PRD §2.5)."""
    q = round2(d)
    return float(q)


def travel_fee(venue_distance_miles):
    """calc travel_fee (PRD §3.2). One-way, free radius then per-mile rate."""
    billable_miles = max(0, venue_distance_miles - TRAVEL_FREE_RADIUS_MILES)
    raw = TRAVEL_RATE_PER_MILE * Decimal(billable_miles)
    return round2(raw)


def _hours_ceil(start, end):
    """Whole-hour span, rounded up (ceil)."""
    seconds = (end - start).total_seconds()
    hours = seconds / 3600.0
    return math.ceil(hours - 1e-9) if hours > 0 else 0


def estimate_quote(booking, package, addon_lines):
    """calc estimate_quote (PRD §3.2). Forward-looking, BOOKED window.

    Returns a Decimal quote_subtotal rounded to 2 dp. Print overage is NOT
    included. Add-on lines are summed from their already-frozen line_totals
    (round-per-line, then sum)."""
    coverage_hours = _hours_ceil(booking["_event_start_dt"], booking["_event_end_dt"])
    overtime_hours = max(0, coverage_hours - package["included_hours"])
    overtime_charge = min(
        Decimal(str(package["overtime_rate_per_hour"])) * Decimal(overtime_hours),
        OVERTIME_DAILY_CAP,
    )

    setup_lead = booking["requested_setup_lead_min"]
    planned_idle_hours = math.ceil(setup_lead / 60.0) if setup_lead > 0 else 0
    idle_charge = Decimal(str(package["idle_rate_per_hour"])) * Decimal(planned_idle_hours)

    addon_total = Decimal("0")
    for line in addon_lines:
        addon_total += round2(Decimal(str(line["line_total"])))

    travel = travel_fee(booking["venue_distance_miles"])

    base_price = Decimal(str(package["base_price"]))
    subtotal = base_price + overtime_charge + idle_charge + addon_total + travel
    return round2(subtotal)


def final_settlement(booking, package, event_log, addon_lines):
    """calc final_settlement (PRD §3.5). Chronological, ACTUAL window, plus
    print overage."""
    cov_start = event_log["_actual_coverage_start_dt"]
    cov_end = event_log["_actual_coverage_end_dt"]
    setup_start = event_log["_actual_setup_start_dt"]

    actual_coverage_hours = (cov_end - cov_start).total_seconds() / 3600.0
    overtime_hours = max(0, math.ceil(actual_coverage_hours - package["included_hours"] - 1e-9))
    overtime_charge = min(
        Decimal(str(package["overtime_rate_per_hour"])) * Decimal(overtime_hours),
        OVERTIME_DAILY_CAP,
    )

    actual_idle_min = (cov_start - setup_start).total_seconds() / 60.0
    idle_hours = math.ceil(actual_idle_min / 60.0 - 1e-9) if actual_idle_min > 0 else 0
    idle_charge = Decimal(str(package["idle_rate_per_hour"])) * Decimal(idle_hours)

    overage_prints = max(0, event_log["actual_print_count"] - package["included_prints"])
    print_overage = round2(Decimal(str(package["overage_print_rate"])) * Decimal(overage_prints))

    addon_total = Decimal("0")
    for line in addon_lines:
        addon_total += round2(Decimal(str(line["line_total"])))

    travel = travel_fee(booking["venue_distance_miles"])

    base_price = Decimal(str(package["base_price"]))
    subtotal = base_price + overtime_charge + idle_charge + addon_total + travel + print_overage
    return round2(subtotal)


def cancellation_refund(booking, now_dt):
    """calc cancellation_refund (PRD §3.7). Returns Decimal refundable_amount."""
    event_start = booking["_event_start_dt"]
    days_to_event = math.floor((event_start - now_dt).total_seconds() / 86400.0)

    if days_to_event >= TIER_FULL_DAYS:
        deposit_refund_pct = Decimal("1.00")
    elif days_to_event >= TIER_HALF_DAYS:
        deposit_refund_pct = Decimal("0.50")
    else:
        deposit_refund_pct = Decimal("0.00")

    deposit_due = Decimal(str(booking["deposit_due"]))
    amount_paid = Decimal(str(booking["amount_paid"]))

    refundable_deposit = round2(deposit_due * deposit_refund_pct)
    refundable_balance = (amount_paid - deposit_due) if amount_paid > deposit_due else Decimal("0")
    refundable_amount = round2(refundable_deposit + refundable_balance)
    return refundable_amount
