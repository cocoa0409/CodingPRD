"""Deterministic calculations and their pinned constants (PRD 2.7, 3.3, 3.5-3.9)."""

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

GRADE_FACTOR = {
    "NEW": Decimal("1.00"),
    "GRADE_A": Decimal("0.85"),
    "GRADE_B": Decimal("0.70"),
    "GRADE_C": Decimal("0.55"),
}
GRADE_STEP_DOWN = {
    "NEW": "GRADE_A",
    "GRADE_A": "GRADE_B",
    "GRADE_B": "GRADE_C",
    "GRADE_C": "GRADE_C",
}
CYCLE_STEP = Decimal("0.05")
CYCLE_FLOOR = Decimal("0.60")
TERM_MARKUP = {"WEEKLY": Decimal("2.20"), "MONTHLY": Decimal("1.95")}
PROCESSING_FEE_PCT = Decimal("0.05")
PERIOD_DAYS = {"WEEKLY": 7, "MONTHLY": 30}
WEEKS_PER_YEAR = 52
MONTHS_PER_YEAR = 12

VERIFICATION_PASS_SCORE = 70
MIN_VERIFIED_REFERENCES = 2
REFERENCE_POINTS_EACH = 10
REFERENCE_POINTS_CAP = 30
RESIDENCE_POINTS_EACH = 5
RESIDENCE_POINTS_CAP = 30
RESIDENCE_MONTHS_PER_STEP = 6
EMPLOYER_VERIFIED_POINTS = 40
INCOME_HIGH_CENTS = 250000
INCOME_MID_CENTS = 150000
INCOME_HIGH_POINTS = 20
INCOME_MID_POINTS = 10

LOYALTY_DISCOUNT_PCT = {
    "STANDARD": Decimal("0.00"),
    "SILVER": Decimal("0.03"),
    "GOLD": Decimal("0.05"),
}
TIER_MULTIPLIER = {"STANDARD": 1, "SILVER": 2, "GOLD": 3}
POINTS_PER_CENTS = 100
ON_TIME_BONUS_POINTS = 25
EARLY_PAYOFF_BONUS_POINTS = 500
SILVER_LIFETIME_MIN = 200
GOLD_LIFETIME_MIN = 500

QUOTE_VALID_DAYS = 7
MISSING_PART_DEDUCTION_CENTS = 2500
RE_RENT_RENEWAL_COUNT = 52
TIER_1_MIN_RATIO = Decimal("0.80")
TIER_2_MIN_RATIO = Decimal("0.60")
ROLLING_WINDOW_DAYS = 7
CREW_TRAVEL_BUFFER_MINUTES = 45


def dec(value):
    """Decimal of a JSON number without inheriting binary float noise."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_up(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_CEILING))


def ratio_4dp(numerator, denominator):
    """paid_pct: a ratio at exactly four decimal places, round half up."""
    if denominator == 0:
        return 0.0
    quantized = (dec(numerator) / dec(denominator)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return float(quantized)


def cycle_factor(rent_cycle_count):
    value = Decimal(1) - CYCLE_STEP * Decimal(rent_cycle_count)
    return value if value > CYCLE_FLOOR else CYCLE_FLOOR


def agreement_pricing(unit, term_type, renewal_count, rule):
    """The ten pinned pricing steps of PRD 3.3."""
    grade = GRADE_FACTOR[unit["condition_grade"]]
    cycle = cycle_factor(unit["rent_cycle_count"])
    adjusted = round_half_up(dec(unit["cash_price_cents"]) * grade * cycle)
    markup = TERM_MARKUP[term_type]
    target_total = round_half_up(dec(adjusted) * markup)
    renewal_rate = round_up(dec(target_total) / dec(renewal_count))
    rent_subtotal = renewal_rate * renewal_count
    fee_from_pct = round_half_up(dec(rent_subtotal) * PROCESSING_FEE_PCT)
    processing_fee = min(rule["processing_fee_max_cents"], fee_from_pct)
    total_of_payments = rent_subtotal + processing_fee
    if term_type == "WEEKLY":
        monthly_equivalent = round_half_up(
            dec(renewal_rate) * Decimal(WEEKS_PER_YEAR) / Decimal(MONTHS_PER_YEAR)
        )
    else:
        monthly_equivalent = renewal_rate
    return {
        "adjusted_cash_price_cents": adjusted,
        "renewal_rate_cents": renewal_rate,
        "rent_subtotal_cents": rent_subtotal,
        "processing_fee_cents": processing_fee,
        "total_of_payments_cents": total_of_payments,
        "monthly_equivalent_rate_cents": monthly_equivalent,
    }


def cost_of_rental_cents(agreement):
    return agreement["total_of_payments_cents"] - agreement["adjusted_cash_price_cents"]


def verification_score(customer):
    """Four independent terms (PRD 3.1)."""
    score = EMPLOYER_VERIFIED_POINTS if customer["employer_verified"] else 0
    steps = customer["residence_months"] // RESIDENCE_MONTHS_PER_STEP
    score += min(RESIDENCE_POINTS_CAP, RESIDENCE_POINTS_EACH * steps)
    score += REFERENCE_POINTS_EACH * min(3, customer["verified_reference_count"])
    income = customer["monthly_income_cents"]
    if income >= INCOME_HIGH_CENTS:
        score += INCOME_HIGH_POINTS
    elif income >= INCOME_MID_CENTS:
        score += INCOME_MID_POINTS
    return score


def late_fee_cents(rule, renewal_rate_cents):
    computed = round_half_up(dec(renewal_rate_cents) * dec(rule["late_fee_pct"]))
    return min(rule["late_fee_max_cents"], computed)


def reinstatement_window_days(rule, agreement):
    threshold = rule["reinstate_threshold_months"] * agreement["monthly_equivalent_rate_cents"]
    if agreement["rent_applied_cents"] >= threshold:
        return rule["reinstate_days_long"]
    return rule["reinstate_days_short"]


def early_purchase_payoff(agreement, rule, rent_applied_snapshot, tier_snapshot):
    """The two statutory payoff variants plus the loyalty discount (PRD 3.8)."""
    formula = rule["early_purchase_formula"]
    if formula == "PCT_OF_REMAINING":
        remaining = agreement["total_of_payments_cents"] - rent_applied_snapshot
        pre_discount = round_half_up(dec(remaining) * dec(rule["early_purchase_pct"]))
    else:
        credit = round_half_up(dec(rent_applied_snapshot) * dec(rule["rent_credit_pct"]))
        pre_discount = agreement["adjusted_cash_price_cents"] - credit
    if pre_discount < 0:
        pre_discount = 0
    discount = round_half_up(dec(pre_discount) * LOYALTY_DISCOUNT_PCT[tier_snapshot])
    late_component = (
        agreement["late_fee_balance_cents"] + agreement["reinstatement_fee_balance_cents"]
    )
    payoff = pre_discount - discount + late_component
    if payoff < 0:
        payoff = 0
    return {
        "formula_applied": formula,
        "pre_discount_cents": pre_discount,
        "loyalty_discount_cents": discount,
        "late_fee_component_cents": late_component,
        "payoff_amount_cents": payoff,
    }


def residual_value_cents(unit, grade_used, deductions_cents):
    """Shared provisional/final residual formula (PRD 3.8)."""
    next_cycle = Decimal(1) - CYCLE_STEP * Decimal(unit["rent_cycle_count"] + 1)
    if next_cycle < CYCLE_FLOOR:
        next_cycle = CYCLE_FLOOR
    base = round_half_up(dec(unit["cash_price_cents"]) * GRADE_FACTOR[grade_used] * next_cycle)
    value = base - deductions_cents
    return value if value > 0 else 0


def provisional_residual_cents(unit):
    return residual_value_cents(unit, GRADE_STEP_DOWN[unit["condition_grade"]], 0)


def final_residual_cents(unit, assessed_grade, damage_deduction_cents, missing_parts_count):
    if assessed_grade == "UNRENTABLE":
        return 0
    deductions = damage_deduction_cents + MISSING_PART_DEDUCTION_CENTS * missing_parts_count
    return residual_value_cents(unit, assessed_grade, deductions)


def re_rent_rate_cents(final_residual):
    marked_up = round_half_up(dec(final_residual) * TERM_MARKUP["WEEKLY"])
    value = round_up(dec(marked_up) / dec(RE_RENT_RENEWAL_COUNT))
    return value if value > 0 else 0


def depreciation_tier(final_residual, cash_price_cents):
    if final_residual == 0:
        return "WRITE_OFF"
    ratio = dec(final_residual) / dec(cash_price_cents)
    if ratio >= TIER_1_MIN_RATIO:
        return "TIER_1"
    if ratio >= TIER_2_MIN_RATIO:
        return "TIER_2"
    return "TIER_3"


def loyalty_tier_for_lifetime(lifetime_points):
    if lifetime_points >= GOLD_LIFETIME_MIN:
        return "GOLD"
    if lifetime_points >= SILVER_LIFETIME_MIN:
        return "SILVER"
    return "STANDARD"


def loyalty_points_for_payment(tier_before, periods_advanced, allocation_rent_cents, days_late):
    if periods_advanced == 0:
        return 0
    points = (allocation_rent_cents // POINTS_PER_CENTS) * TIER_MULTIPLIER[tier_before]
    if days_late == 0:
        points += ON_TIME_BONUS_POINTS
    return points
