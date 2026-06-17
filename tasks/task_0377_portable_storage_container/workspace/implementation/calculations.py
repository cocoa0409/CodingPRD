"""All calculation rules from scaffold §1.3 / PRD §3. Money is integer cents;
fractional cents are rounded half-up to a whole cent. We use Decimal exclusively
for any division/percentage so IEEE-754 float error never enters.
"""
import calendar
from decimal import Decimal, ROUND_HALF_UP

# move_pricing constants (scaffold §1.3)
LOCAL_BASE_CENTS = 8900
LOCAL_PER_MILE_CENTS = 350
BAND1_CENTS = 180
BAND2_CENTS = 140
BAND3_CENTS = 110
FUEL_SURCHARGE_PCT = Decimal("0.12")
HANDLING_PER_CONTAINER_CENTS = 12500

# late_fee constants
GRACE_DAYS = 5
DELINQUENT_DAYS = 20
TIER1_SPAN_DAYS = 10
LATE_FLAT_CENTS = 2500
DAILY1_CENTS = 200
DAILY2_CENTS = 500
LATE_CAP_PCT = Decimal("0.50")

BPS_DIVISOR = Decimal(10000)


def round_half_up(value):
    """Round a Decimal to the nearest whole integer, half away from zero (up)."""
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# rental_proration
# --------------------------------------------------------------------------
def rental_proration(monthly_rate_cents, anchor_dt, proration_method):
    """First-cycle proration (PRD §3.4). anchor_dt is the delivery_anchor_date."""
    year = anchor_dt.year
    month = anchor_dt.month
    d = anchor_dt.day
    days_in_month = calendar.monthrange(year, month)[1]
    days_billed = days_in_month - d + 1  # delivery day inclusive through month end
    monthly = Decimal(monthly_rate_cents)
    if proration_method == "FIXED_30":
        divisor = Decimal(30)
    else:  # CALENDAR_DAY
        divisor = Decimal(days_in_month)
    return round_half_up(monthly * Decimal(days_billed) / divisor)


# --------------------------------------------------------------------------
# protection_premium
# --------------------------------------------------------------------------
def protection_premium(plan, declared_value_cents):
    """Monthly protection premium locked at activation (PRD §3.4)."""
    rate_component = round_half_up(
        Decimal(plan["rate_bps"]) * Decimal(declared_value_cents) / BPS_DIVISOR
    )
    raw = plan["base_premium_cents"] + rate_component
    return max(raw, plan["min_premium_cents"])


# --------------------------------------------------------------------------
# move_pricing
# --------------------------------------------------------------------------
def classify_move(distance_miles, service_radius_miles):
    """LOCAL if distance <= radius (boundary inclusive), else LONG_DISTANCE."""
    return "LOCAL" if distance_miles <= service_radius_miles else "LONG_DISTANCE"


def move_pricing(distance_miles, move_class):
    """Quoted cost in cents (PRD §3.6). One container per move."""
    if move_class == "LOCAL":
        return LOCAL_BASE_CENTS + LOCAL_PER_MILE_CENTS * distance_miles
    # LONG_DISTANCE: marginal bands + fuel surcharge + per-container handling
    b1 = min(distance_miles, 500)
    b2 = max(0, min(distance_miles, 1500) - 500)
    b3 = max(0, distance_miles - 1500)
    mileage_cents = BAND1_CENTS * b1 + BAND2_CENTS * b2 + BAND3_CENTS * b3
    fuel_cents = round_half_up(Decimal(mileage_cents) * FUEL_SURCHARGE_PCT)
    handling_cents = HANDLING_PER_CONTAINER_CENTS * 1
    return mileage_cents + fuel_cents + handling_cents


# --------------------------------------------------------------------------
# packing_supplies_total
# --------------------------------------------------------------------------
def packing_supplies_total(lines, tax_rate_bps):
    """subtotal/tax/total (PRD §3.7): round discount per line, sum nets,
    then tax once on the summed subtotal."""
    subtotal = 0
    for ln in lines:
        qty = ln["qty"]
        unit_price = ln["unit_price_cents"]
        gross = qty * unit_price
        if qty >= ln["bulk_threshold"]:
            disc = round_half_up(Decimal(gross) * Decimal(str(ln["bulk_pct"])))
        else:
            disc = 0
        subtotal += gross - disc
    tax = round_half_up(Decimal(subtotal) * Decimal(tax_rate_bps) / BPS_DIVISOR)
    total = subtotal + tax
    return subtotal, tax, total


# --------------------------------------------------------------------------
# late_fee
# --------------------------------------------------------------------------
def late_fee_gross(days_overdue):
    """Gross late fee (before cap) for a given days_overdue (PRD §3.9)."""
    if days_overdue <= GRACE_DAYS:
        return 0
    eff = days_overdue - GRACE_DAYS
    d1 = min(eff, TIER1_SPAN_DAYS)
    d2 = max(0, eff - TIER1_SPAN_DAYS)
    return LATE_FLAT_CENTS + DAILY1_CENTS * d1 + DAILY2_CENTS * d2


def late_fee_cap(balance_due_cents):
    return round_half_up(Decimal(balance_due_cents) * LATE_CAP_PCT)


def late_fee_capped(days_overdue, balance_due_cents):
    gross = late_fee_gross(days_overdue)
    if gross == 0:
        return 0
    cap = late_fee_cap(balance_due_cents)
    return min(gross, cap)
