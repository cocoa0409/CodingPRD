"""The nine calculations of SCAFFOLD.calculations / PRD 3."""
from decimal import Decimal
from fractions import Fraction

from numeric import frac, rhu, rhu_int

# --------------------------------------------------------------------------- #
# accountability_representation_score (PRD 3.1)
# --------------------------------------------------------------------------- #
ADVISORY_WEIGHT = Fraction(1, 2)
ADVISORY_CREDIT_CAP = Fraction(1, 5)          # 0.2000
SATISFACTION_THRESHOLD = Decimal("0.5000")


def accountability_score(gov_total, gov_representing, adv_total, adv_representing):
    if gov_total == 0:
        governing_pct = Fraction(0)
    else:
        governing_pct = Fraction(gov_representing, gov_total)     # exact, unrounded
    combined = gov_total + adv_total
    if combined == 0:
        advisory_credit = Fraction(0)
    else:
        advisory_credit = min(
            ADVISORY_CREDIT_CAP,
            ADVISORY_WEIGHT * Fraction(adv_representing, combined),
        )
    total = governing_pct + advisory_credit
    if total > 1:
        total = Fraction(1)
    score = rhu(total, 4)
    return score, score >= SATISFACTION_THRESHOLD


# --------------------------------------------------------------------------- #
# target_market_attribution (PRD 3.3)
# --------------------------------------------------------------------------- #
MARKET_TYPE_PRECEDENCE = {
    "INVESTMENT_AREA": 1,
    "LOW_INCOME_TARGETED_POPULATION": 2,
    "OTHER_TARGETED_POPULATION": 3,
}


def income_pct_ami(household_income_cents, area_median_income_cents):
    if area_median_income_cents == 0:
        return Decimal("0.00")
    return rhu(Fraction(100 * household_income_cents, area_median_income_cents), 2)


def attribution_predicate(market, borrower):
    kind = market["market_type"]
    if kind == "INVESTMENT_AREA":
        code = borrower.get("census_tract_code")
        return code is not None and code in (market.get("census_tract_codes") or [])
    if kind == "LOW_INCOME_TARGETED_POPULATION":
        ceiling = market.get("ami_threshold_pct")
        if ceiling is None:
            return False
        return borrower.get("income_pct_ami") <= ceiling
    if kind == "OTHER_TARGETED_POPULATION":
        return borrower.get("credit_score") is None
    return False


# --------------------------------------------------------------------------- #
# loan_pricing_and_grade (PRD 3.5)
# --------------------------------------------------------------------------- #
RISK_SPREAD_BPS = {"A": 0, "B": 75, "C": 150, "D": 275, "E": 200}
TA_DISCOUNT_BPS = 25
TA_DISCOUNT_HOURS_THRESHOLD = Decimal("8.00")
TIER_E_HOURS_THRESHOLD = Decimal("12.00")


def simple_declining_payment(principal_cents, rate_bps, term_months):
    """One month of simple interest on the full principal plus straight-line
    principal, rounded half up to whole cents once at the end of the step."""
    interest = Fraction(principal_cents) * Fraction(rate_bps, 10000) / 12
    amortized = Fraction(principal_cents, term_months)
    return rhu_int(interest + amortized)


def debt_to_income(existing_monthly_debt_cents, payment_cents,
                   verified_monthly_income_cents):
    if verified_monthly_income_cents <= 0:
        return None
    numerator = 100 * (existing_monthly_debt_cents + payment_cents)
    return rhu(Fraction(numerator, verified_monthly_income_cents), 2)


def resolve_tier(credit_score, dti_pct, product, ta_hours_total):
    """Walk the five tiers top to bottom; the first that matches wins."""
    if credit_score is not None:
        if credit_score >= 720 and dti_pct <= Decimal("36.00"):
            return "A"
        if credit_score >= 660 and dti_pct <= Decimal("43.00"):
            return "B"
        if credit_score >= 600 and dti_pct <= Decimal("45.00"):
            return "C"
        if credit_score >= product["min_credit_score"] and dti_pct <= Decimal("50.00"):
            return "D"
        return None
    if (product["allow_no_credit_score"]
            and ta_hours_total >= TIER_E_HOURS_THRESHOLD
            and dti_pct <= Decimal("45.00")):
        return "E"
    return None


def ta_discount_bps(ta_hours_total):
    return TA_DISCOUNT_BPS if ta_hours_total >= TA_DISCOUNT_HOURS_THRESHOLD else 0


# --------------------------------------------------------------------------- #
# portfolio_loss_reserve (PRD 3.6)
# --------------------------------------------------------------------------- #
ROLL_RATE = {
    "CURRENT": Fraction(2, 100),
    "DELINQUENT_30": Fraction(10, 100),
    "DELINQUENT_60": Fraction(35, 100),
    "DELINQUENT_90": Fraction(75, 100),
}
VINTAGE_RATE_CURRENT_YEAR = Fraction(45, 1000)      # 0.0450
VINTAGE_RATE_PRIOR_YEAR = Fraction(3, 100)          # 0.0300


def migration_reserve(loans):
    """Exact products summed, then a single rounding to whole cents."""
    total = Fraction(0)
    for loan in loans:
        rate = ROLL_RATE.get(loan["servicing_state"])
        if rate is None:
            continue
        total += Fraction(loan["principal_outstanding_cents"]) * rate
    return rhu_int(total)


def static_pool_reserve(loans, clock_year):
    total = Fraction(0)
    for loan in loans:
        disbursed = loan["principal_disbursed_cents"]
        if disbursed <= 0:
            continue
        rate = (VINTAGE_RATE_CURRENT_YEAR
                if loan.get("vintage_year") == clock_year
                else VINTAGE_RATE_PRIOR_YEAR)
        total += Fraction(disbursed) * rate
    return rhu_int(total)


# --------------------------------------------------------------------------- #
# reserve_coverage_and_posture (PRD 2.11)
# --------------------------------------------------------------------------- #
POSTURE_COMPLIANT_MIN_RATIO = Decimal("1.0000")
POSTURE_WATCH_MIN_RATIO = Decimal("0.8000")
EMPTY_PORTFOLIO_RATIO = Decimal("1.0000")


def coverage_ratio(balance_cents, required_cents):
    if required_cents == 0:
        return EMPTY_PORTFOLIO_RATIO
    return rhu(Fraction(balance_cents, required_cents), 4)


def posture_for(ratio):
    if ratio >= POSTURE_COMPLIANT_MIN_RATIO:
        return "COMPLIANT"
    if ratio >= POSTURE_WATCH_MIN_RATIO:
        return "WATCH"
    return "PROBATION"


# --------------------------------------------------------------------------- #
# award_eligible_match_total (PRD 3.9)
# --------------------------------------------------------------------------- #
SOURCE_FACTOR = {
    "CASH_PRIVATE": Fraction(1),
    "CASH_PUBLIC_NON_FEDERAL": Fraction(1),
    "IN_KIND": Fraction(1, 2),
    "DEFERRED_PLEDGE": Fraction(3, 4),
    "FEDERAL": Fraction(0),
}


def commitment_eligible_cents(amount_cents, source_type):
    """Rounded per commitment -- the opposite order to the reserve calculation."""
    return rhu_int(Fraction(amount_cents) * SOURCE_FACTOR[source_type])


def required_match_cents(requested_amount_cents, match_ratio_pct):
    return rhu_int(Fraction(requested_amount_cents) * frac(match_ratio_pct) / 100)


# --------------------------------------------------------------------------- #
# institution_impact_aggregation (PRD 3.7)
# --------------------------------------------------------------------------- #
GOAL_DENOMINATOR_FLOOR = 1


def goal_attainment_pct(jobs_created_total, housing_units_total,
                        performance_goal_jobs, performance_goal_housing_units):
    denominator = max(GOAL_DENOMINATOR_FLOOR,
                      performance_goal_jobs + performance_goal_housing_units)
    numerator = 100 * (jobs_created_total + housing_units_total)
    return rhu(Fraction(numerator, denominator), 2)


# --------------------------------------------------------------------------- #
# target_market_lending_percentage (PRD 3.8)
# --------------------------------------------------------------------------- #
TARGET_MARKET_THRESHOLD_PCT = Decimal("60.00")
RECERTIFICATION_INTERVAL_DAYS = 1095


def weighted_pct(numerator, denominator):
    if denominator == 0:
        return Decimal("0.00")
    return rhu(Fraction(100 * numerator, denominator), 2)


# --------------------------------------------------------------------------- #
# delinquency_bucket_assignment (PRD 3.6)
# --------------------------------------------------------------------------- #
BUCKET_ORDER = {
    "CURRENT": 0,
    "DELINQUENT_30": 1,
    "DELINQUENT_60": 2,
    "DELINQUENT_90": 3,
}
PAYMENT_PERIOD_DAYS = 30


def bucket_for(days_past_due):
    if days_past_due >= 90:
        return "DELINQUENT_90"
    if days_past_due >= 60:
        return "DELINQUENT_60"
    if days_past_due >= 30:
        return "DELINQUENT_30"
    return None


def whole_days_past_due(due_at, clock):
    """Whole days from next_payment_due_on to the clock, truncated, floored at 0."""
    if due_at is None:
        return 0
    delta = clock - due_at
    days = int(delta.total_seconds() // 86400) if delta.total_seconds() >= 0 else 0
    return max(0, days)
