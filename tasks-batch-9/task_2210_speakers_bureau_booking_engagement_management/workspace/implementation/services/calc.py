"""Calculation rules (PRD §3.6 - §3.9, scaffold §1.3).

All money is integer cents; every rate multiplication is rounded half up at the
granularity the PRD pins for that calculation.
"""

from decimal import Decimal, ROUND_HALF_UP

# --- constants --------------------------------------------------------------
SURCHARGE_PCT = Decimal("0.0175")

MIN_LEAD_DAYS = 21
MIN_BUDGET_CENTS = 250000
BUDGET_TOLERANCE = Decimal("1.20")

MAX_REVISION_ROUNDS = 2
MAX_OPTIONS = 4

COMMISSION_PCT_MIN = Decimal("0.10")
COMMISSION_PCT_MAX = Decimal("0.35")

STANDARD_FULL_WAIVER_DAYS = 30
STANDARD_HALF_RETENTION_DAYS = 14
STRICT_QUARTER_RETENTION_DAYS = 60
STRICT_THREE_QUARTER_RETENTION_DAYS = 21

REBATE_HIGH_THRESHOLD_CENTS = 500000
REBATE_LOW_THRESHOLD_CENTS = 200000
REBATE_HIGH_PCT = Decimal("0.10")
REBATE_LOW_PCT = Decimal("0.05")

DISTANCE_BAND_RATE_CENTS_PER_DAY = {
    "LOCAL": 15000,
    "REGIONAL": 45000,
    "NATIONAL": 90000,
    "INTERNATIONAL": 180000,
}
TRAVEL_CLASS_MULT = {
    "ECONOMY": Decimal("1.00"),
    "PREMIUM": Decimal("1.25"),
    "BUSINESS": Decimal("1.60"),
}

CONTENT_WEIGHT = Decimal("0.6")
LOGISTICS_WEIGHT = Decimal("0.4")
ROLLING_WEIGHTS = [Decimal("0.5"), Decimal("0.3"), Decimal("0.2")]
ROLLING_WINDOW = 3

SILVER_MIN_DELIVERED = 2
SILVER_MIN_ROLLING_SCORE = Decimal("4.00")
GOLD_MIN_DELIVERED = 4
GOLD_MIN_ROLLING_SCORE = Decimal("4.50")
TIER_COMMISSION_PCT = {
    "BRONZE": Decimal("0.25"),
    "SILVER": Decimal("0.22"),
    "GOLD": Decimal("0.20"),
}

PROTECTION_FULL_DAYS = 180
NON_CIRCUMVENTION_DAYS = 365
PROTECTION_FULL_FACTOR = Decimal("1.00")
PROTECTION_TAIL_FACTOR = Decimal("0.50")
CREDIT_HOLD_STRIKE_THRESHOLD = 2


# --- primitives -------------------------------------------------------------

def dec(value):
    """Exact Decimal from an int/float/str/Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up_cents(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(value):
    return dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# --- engagement_commission --------------------------------------------------

def provisional_commission(quoted_fee_cents, commission_pct):
    return round_half_up_cents(dec(quoted_fee_cents) * dec(commission_pct))


def final_commission(quoted_fee_cents, recording_fee_cents, commission_pct):
    base = dec(quoted_fee_cents) + dec(recording_fee_cents)
    return round_half_up_cents(base * dec(commission_pct))


# --- invoice_surcharge_rounding ---------------------------------------------

def invoice_surcharge(fee_line_cents, recording_line_cents, travel_line_cents):
    """Round EACH line, THEN sum the rounded parts (order is normative)."""
    s_fee = round_half_up_cents(dec(fee_line_cents) * SURCHARGE_PCT)
    s_recording = round_half_up_cents(dec(recording_line_cents) * SURCHARGE_PCT)
    s_travel = round_half_up_cents(dec(travel_line_cents) * SURCHARGE_PCT)
    return s_fee + s_recording + s_travel


# --- cancellation_settlement ------------------------------------------------

def retention_pct(schedule_code, days_before):
    if schedule_code == "STRICT":
        if days_before >= STRICT_QUARTER_RETENTION_DAYS:
            return Decimal("0.25")
        if days_before >= STRICT_THREE_QUARTER_RETENTION_DAYS:
            return Decimal("0.75")
        return Decimal("1.00")
    # STANDARD
    if days_before >= STANDARD_FULL_WAIVER_DAYS:
        return Decimal("0.00")
    if days_before >= STANDARD_HALF_RETENTION_DAYS:
        return Decimal("0.50")
    return Decimal("1.00")


def rebate_pct_for_gross(gross_retention_cents):
    if gross_retention_cents >= REBATE_HIGH_THRESHOLD_CENTS:
        return REBATE_HIGH_PCT
    if gross_retention_cents >= REBATE_LOW_THRESHOLD_CENTS:
        return REBATE_LOW_PCT
    return Decimal("0.00")


def cancellation_settlement(quoted_fee_cents, schedule_code, days_before, commission_pct):
    """Six order-pinned steps.  Returns (retention_net, retention_commission)."""
    pct = retention_pct(schedule_code, days_before)                      # step 2
    gross = round_half_up_cents(dec(quoted_fee_cents) * pct)             # step 3
    rebate = round_half_up_cents(dec(gross) * rebate_pct_for_gross(gross))  # step 4
    net = gross - rebate                                                # step 5
    commission = round_half_up_cents(dec(net) * dec(commission_pct))     # step 6
    return net, commission


# --- travel_reimbursable ----------------------------------------------------

def travel_reimbursable(is_virtual, travel_policy_code, allowance_cents,
                        receipts_cents, travel_days, distance_band, travel_class):
    if is_virtual:
        return 0
    if travel_policy_code == "POLICY_A":
        schedule = round_half_up_cents(
            dec(DISTANCE_BAND_RATE_CENTS_PER_DAY[distance_band])
            * dec(travel_days)
            * TRAVEL_CLASS_MULT[travel_class]
        )
        ceiling = max(allowance_cents, schedule)
        return min(receipts_cents, ceiling)
    ceiling = allowance_cents
    return min(receipts_cents, ceiling)


# --- speaker_performance_score ---------------------------------------------

def composite_score(content_score, logistics_score):
    return round_half_up_2(
        CONTENT_WEIGHT * dec(content_score) + LOGISTICS_WEIGHT * dec(logistics_score)
    )


def lifetime_score(composites):
    if not composites:
        return None
    total = sum((dec(c) for c in composites), Decimal(0))
    return round_half_up_2(total / Decimal(len(composites)))


def rolling_score(composites):
    """`composites` must already be ordered newest-first."""
    if not composites:
        return None
    take = min(ROLLING_WINDOW, len(composites))
    raw = ROLLING_WEIGHTS[:take]
    total_weight = sum(raw, Decimal(0))
    acc = Decimal(0)
    for index in range(take):
        weight = raw[index] / total_weight
        acc += weight * dec(composites[index])
    return round_half_up_2(acc)


# --- roster_tier_assignment -------------------------------------------------

def roster_tier(delivered_count, rolling):
    if rolling is not None:
        score = dec(rolling)
        if delivered_count >= GOLD_MIN_DELIVERED and score >= GOLD_MIN_ROLLING_SCORE:
            return "GOLD"
        if delivered_count >= SILVER_MIN_DELIVERED and score >= SILVER_MIN_ROLLING_SCORE:
            return "SILVER"
    return "BRONZE"


# --- circumvention_commission_due ------------------------------------------

def protection_factor(days_after_source):
    if days_after_source <= PROTECTION_FULL_DAYS:
        return PROTECTION_FULL_FACTOR
    if days_after_source <= NON_CIRCUMVENTION_DAYS:
        return PROTECTION_TAIL_FACTOR
    return None


def circumvention_commission_due(direct_fee_cents, commission_pct, factor):
    return round_half_up_cents(dec(direct_fee_cents) * dec(commission_pct) * dec(factor))


# --- budget headroom --------------------------------------------------------

def budget_ceiling_cents(budget_cents):
    return round_half_up_cents(dec(budget_cents) * BUDGET_TOLERANCE)
