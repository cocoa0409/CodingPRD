"""Calculation engine — all money math, Decimal + ROUND_HALF_UP.

Every formula is implemented verbatim from PRD Section 3 and the scaffold
calculations table. Never use float arithmetic for the rounded result.
"""

from decimal import Decimal, ROUND_HALF_UP


# --- constants (from scaffold calculations table) ---
OT_THRESHOLD_HOURS = Decimal("40")
OT_MULTIPLIER = Decimal("1.5")
OT_BILL_MULTIPLIER = Decimal("1.5")

# invoice_total tiers
TIER_1_MIN_CENTS = 500000      # 500000 <= subtotal < 2000000 -> 3%
TIER_1_RATE = Decimal("0.03")
TIER_2_MIN_CENTS = 2000000     # subtotal >= 2000000 -> 6%
TIER_2_RATE = Decimal("0.06")
PROCESSING_FEE_PCT = Decimal("0.015")

# conversion_fee
TENURE_DISCOUNT_WEEKS = 13
TENURE_DISCOUNT_FACTOR = Decimal("0.5")
MIN_FEE_CENTS = 250000
MAX_FEE_CENTS = 5000000


def round_half_up(value):
    """Round a Decimal to whole cents, half rounding upward."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _dec_hours(hours):
    # hours arrives as int or float; render exactly via str to avoid binary
    # float artifacts before Decimal arithmetic.
    return Decimal(str(hours))


def timesheet_pay(hours, pay_rate_cents):
    """PRD 3.6 / scaffold timesheet_pay.

    regular_hours  = min(hours, 40)
    overtime_hours = max(0, hours - 40)
    pay = round_half_up(regular*rate + overtime*rate*1.5)
    Overtime applies STRICTLY above 40; hours == 40.0 -> 0 overtime.
    Sum-then-round.
    """
    h = _dec_hours(hours)
    regular = min(h, OT_THRESHOLD_HOURS)
    overtime = max(Decimal("0"), h - OT_THRESHOLD_HOURS)
    rate = Decimal(pay_rate_cents)
    raw = regular * rate + overtime * rate * OT_MULTIPLIER
    return round_half_up(raw)


def timesheet_bill(hours, bill_rate_cents):
    """PRD 3.6 / scaffold timesheet_bill. Sum-then-round."""
    h = _dec_hours(hours)
    regular = min(h, OT_THRESHOLD_HOURS)
    overtime = max(Decimal("0"), h - OT_THRESHOLD_HOURS)
    rate = Decimal(bill_rate_cents)
    raw = regular * rate + overtime * rate * OT_BILL_MULTIPLIER
    return round_half_up(raw)


def tier_rate(subtotal_cents):
    """Volume-discount tier rate selected by inclusive lower boundary."""
    if subtotal_cents >= TIER_2_MIN_CENTS:
        return TIER_2_RATE
    if subtotal_cents >= TIER_1_MIN_CENTS:
        return TIER_1_RATE
    return Decimal("0")


def invoice_total(line_total_cents_list):
    """PRD 3.8 / scaffold invoice_total. Pinned 5-step order.

    STEP 1  subtotal = sum of already-rounded per-line totals (round-per-line
            then sum; line totals were rounded when copied from bill_cents).
    STEP 2  volume_discount = round_half_up(subtotal * tier_rate(subtotal))
    STEP 3  discounted = subtotal - volume_discount
    STEP 4  processing_fee = round_half_up(discounted * 0.015)  (post-discount)
    STEP 5  total = subtotal - volume_discount + processing_fee
    Returns (subtotal, volume_discount, processing_fee, total).
    """
    subtotal = sum(line_total_cents_list)
    rate = tier_rate(subtotal)
    volume_discount = round_half_up(Decimal(subtotal) * rate)
    discounted = subtotal - volume_discount
    processing_fee = round_half_up(Decimal(discounted) * PROCESSING_FEE_PCT)
    total = subtotal - volume_discount + processing_fee
    return subtotal, volume_discount, processing_fee, total


def conversion_fee(base_cents, conversion_fee_pct, placement_type, weeks_worked):
    """PRD 3.7 / scaffold conversion_fee.

    DIRECT:        effective_pct = client.conversion_fee_pct
    TEMP_TO_PERM:  effective_pct = client.conversion_fee_pct * tenure_factor
        tenure_factor = 1.0 if weeks_worked < 13 else 0.5
    raw_fee   = round_half_up(base * effective_pct)
    fee_cents = max(MIN, min(raw, MAX))   (round before clamp)
    """
    pct = Decimal(str(conversion_fee_pct))
    if placement_type == "DIRECT":
        effective = pct
    else:  # TEMP_TO_PERM
        if weeks_worked < TENURE_DISCOUNT_WEEKS:
            tenure_factor = Decimal("1.0")
        else:
            tenure_factor = TENURE_DISCOUNT_FACTOR
        effective = pct * tenure_factor
    raw = round_half_up(Decimal(base_cents) * effective)
    clamped = max(MIN_FEE_CENTS, min(raw, MAX_FEE_CENTS))
    return clamped


def projected_weekly_bill(bill_rate_cents, standard_weekly_hours, placement_type):
    """PRD 3.6: bill_rate * standard_weekly_hours; 0 for DIRECT. Exact integer."""
    if placement_type == "DIRECT":
        return 0
    return bill_rate_cents * standard_weekly_hours


def projected_weekly_margin(bill_rate_cents, pay_rate_cents, standard_weekly_hours, placement_type):
    """PRD 3.6: (bill_rate - pay_rate) * standard_weekly_hours; 0 for DIRECT."""
    if placement_type == "DIRECT":
        return 0
    return (bill_rate_cents - pay_rate_cents) * standard_weekly_hours
