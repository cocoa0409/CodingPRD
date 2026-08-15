"""Calculation rules (PRD section 3, scaffold Table 3).

All money is integer cents, rounded half-up. Fractional measures
(credibility, renewal increase, AV, relativity, enrollment change pct) are
rounded half-up to 4 decimal places. completion_ratio is an exact 2-decimal
lookup.
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING


def D(x):
    return Decimal(str(x))


def round_cents(x):
    """Round half-up to whole cents, return int."""
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round4(x):
    """Round half-up to 4 decimal places, return float."""
    return float(D(x).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


# --- Credibility (PRD 3.2) ---
MIN_GROUP_SIZE = 25
FULL_CREDIBILITY_SIZE = 500
MIN_EXPERIENCE_MONTHS = 12
FULL_EXPERIENCE_MONTHS = 24


def group_size_factor(group_size):
    if group_size < MIN_GROUP_SIZE:
        return Decimal("0")
    if group_size < 100:
        return D(group_size) / D(100)
    if group_size < FULL_CREDIBILITY_SIZE:
        return D(group_size) / D(500)
    return Decimal("1")


def months_factor(months):
    if months is None:
        return None
    if months < MIN_EXPERIENCE_MONTHS:
        return Decimal("0")
    if months < FULL_EXPERIENCE_MONTHS:
        return D(months) / D(24)
    return Decimal("1")


def credibility_from_census(group_size):
    """At census validation no claims experience exists yet, so the months
    factor contributes nothing and credibility reflects size alone (PRD 3.2)."""
    return round4(min(Decimal("1"), group_size_factor(group_size)))


def credibility_blended(group_size, months):
    """Z = min(group_size_factor, months_factor), capped at 1.0, 4 dp."""
    z = min(group_size_factor(group_size), months_factor(months))
    z = min(Decimal("1"), z)
    return round4(z)


# --- Manual rate (PRD 3.2) ---
BASE_MANUAL_RATE_CENTS = 45000


def age_factor(avg_age):
    a = D(avg_age)
    if a < 30:
        return Decimal("0.85")
    if a < 40:
        return Decimal("1.00")
    if a < 50:
        return Decimal("1.15")
    if a < 60:
        return Decimal("1.35")
    return Decimal("1.60")


def gender_factor(ratio):
    r = D(ratio)
    if r < D("0.40"):
        return Decimal("0.95")
    if r <= D("0.60"):
        return Decimal("1.00")
    return Decimal("1.08")


def industry_factor(sic_code):
    try:
        prefix = int(str(sic_code)[:2])
    except (ValueError, TypeError):
        return Decimal("1.00")
    if 1 <= prefix <= 9:
        return Decimal("0.90")
    if 10 <= prefix <= 14:
        return Decimal("1.10")
    if 15 <= prefix <= 17:
        return Decimal("1.05")
    if 20 <= prefix <= 39:
        return Decimal("1.00")
    if 40 <= prefix <= 49:
        return Decimal("1.02")
    if 50 <= prefix <= 59:
        return Decimal("0.98")
    if 60 <= prefix <= 67:
        return Decimal("0.95")
    if 70 <= prefix <= 89:
        return Decimal("1.00")
    if 91 <= prefix <= 97:
        return Decimal("0.97")
    return Decimal("1.00")


def manual_rate(avg_age, gender_ratio, sic_code):
    af = age_factor(avg_age) if avg_age is not None else Decimal("1.00")
    gf = gender_factor(gender_ratio) if gender_ratio is not None else Decimal("1.00")
    inf = industry_factor(sic_code)
    return round_cents(D(BASE_MANUAL_RATE_CENTS) * af * gf * inf)


# --- Claims derived fields (PRD 3.3) ---
def whole_months_inclusive(start, end):
    """Count of whole months between start and end, inclusive."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months + 1


def pooled_claims(total_paid, large_claim_count, pooling_threshold):
    """Portion of paid claims sitting above the pooling threshold: each large
    claim is capped at the threshold and the excess is pooled away."""
    if large_claim_count <= 0:
        return 0
    pooled = D(total_paid) - D(large_claim_count) * D(pooling_threshold)
    if pooled < 0:
        pooled = Decimal("0")
    return round_cents(pooled)


def completion_ratio(months):
    """IBNR completion factor — exact 2-decimal lookup."""
    if months >= 24:
        return Decimal("1.00")
    if months >= 18:
        return Decimal("0.98")
    if months >= 12:
        return Decimal("0.95")
    return Decimal("0.85")


# --- Experience rate (PRD 3.3) ---
ANNUAL_TREND = Decimal("0.065")
RETENTION_PCT = Decimal("0.15")


def experience_rate(net_claim_cost, completion, total_enrollment_months, credibility):
    adjusted = D(net_claim_cost) / completion
    trended = adjusted * ((Decimal("1") + ANNUAL_TREND) ** 2)
    pepm = trended / D(total_enrollment_months)
    rate = pepm / (Decimal("1") - RETENTION_PCT)
    # Conservative variant: thin experience (credibility < 0.5) adds 10% load
    if D(credibility) < D("0.5"):
        rate = rate * D("1.10")
    return round_cents(rate)


# --- Blended rate with rate cap (PRD 3.3) ---
DEFAULT_RATE_CAP_PCT = 0.15


def blended_rate(credibility, experience, manual, current_premium_annual,
                 enrolled_employees, cap_pct):
    z = D(credibility)
    raw = z * D(experience) + (Decimal("1") - z) * D(manual)
    max_rate = (
        D(current_premium_annual) / D(12) / D(enrolled_employees)
        * (Decimal("1") + D(cap_pct))
    )
    if raw > max_rate:
        return round_cents(max_rate), True
    return round_cents(raw), False


# --- Plan modeling (PRD 3.4) ---
def actuarial_value(ded_ind, coinsurance_pct, oop_ind, copay_primary, copay_specialist):
    av = Decimal("1.0")
    av -= (D(ded_ind) / D(50000)) * D("0.02")
    av = av * (D("0.60") + D("0.40") * D(coinsurance_pct))
    oop_excess = (D(oop_ind) - D(200000)) / D(100000)
    if oop_excess < 0:
        oop_excess = Decimal("0")
    av -= oop_excess * D("0.005")
    av -= (D(copay_primary + copay_specialist) / D(100000)) * D("0.01")
    if av < D("0.50"):
        av = D("0.50")
    if av > D("1.00"):
        av = D("1.00")
    return round4(av)


def relativity_factor(is_reference, own_av, reference_av):
    if is_reference:
        return 1.0
    if reference_av is None or D(reference_av) == 0:
        return 1.0
    return round4(D(own_av) / D(reference_av))


# --- Quote pricing (PRD 3.5) ---
def quote_pepm(blended_rate_cents, relativity):
    return round_cents(D(blended_rate_cents) * D(relativity))


def level_funded_split(pepm):
    """82% claims fund / 12% admin / 6% stop-loss; components must sum back
    exactly to the whole PEPM."""
    claims_fund = round_cents(D(pepm) * D("0.82"))
    admin_fee = round_cents(D(pepm) * D("0.12"))
    stop_loss = pepm - claims_fund - admin_fee
    return claims_fund, admin_fee, stop_loss


def annual_premium(pepm, enrolled_employees):
    return round_cents(D(pepm) * D(12) * D(enrolled_employees))


def renewal_increase_pct(annual_premium_cents, current_premium_annual):
    if D(current_premium_annual) == 0:
        return 0.0
    return round4(
        (D(annual_premium_cents) - D(current_premium_annual))
        / D(current_premium_annual)
    )


def broker_commission(annual_premium_cents, commission_pct):
    return round_cents(D(annual_premium_cents) * D(commission_pct))


DISCLOSURE_THRESHOLD_PER_ENROLLEE_CENTS = 5000


def commission_disclosure_required(commission_cents, enrolled_employees):
    if enrolled_employees <= 0:
        return False
    return (D(commission_cents) / D(enrolled_employees)) >= D(
        DISCLOSURE_THRESHOLD_PER_ENROLLEE_CENTS
    )


# --- Stop-loss pricing (PRD 3.7) ---
CLAIMS_FUND_SHARE = Decimal("0.82")
AGGREGATE_RATE = Decimal("0.02")
LASER_LOAD_PCT = Decimal("0.25")


def expected_annual_claims(rate_cents, enrolled_employees):
    return round_cents(D(rate_cents) * D(12) * D(enrolled_employees) * CLAIMS_FUND_SHARE)


def aggregate_attachment(expected_claims, attachment_pct):
    return round_cents(D(expected_claims) * D(attachment_pct))


def specific_rate_per_1000(specific_deductible):
    if specific_deductible <= 2500000:
        return D(850)
    if specific_deductible <= 5000000:
        return D(620)
    if specific_deductible <= 10000000:
        return D(410)
    return D(280)


def specific_premium(specific_deductible, enrolled_employees):
    rate = specific_rate_per_1000(specific_deductible)
    return round_cents(
        (D(specific_deductible) / D(1000)) * rate * D(enrolled_employees) / D(100)
    )


def aggregate_premium(attachment_cents):
    return round_cents(D(attachment_cents) * AGGREGATE_RATE)


def apply_laser_load(specific_premium_cents):
    return round_cents(D(specific_premium_cents) * (Decimal("1") + LASER_LOAD_PCT))


# --- Enrollment impact (PRD 3.8) ---
def enrollment_impact(enrolled_employees, change_count, threshold):
    revised = enrolled_employees + change_count
    if enrolled_employees == 0:
        pct = Decimal("0")
    else:
        pct = D(change_count) / D(enrolled_employees)
    pct = D(round4(pct))
    thr = D(threshold)
    if abs(pct) > thr:
        excess = abs(pct) - thr
        bands = int((excess / D("0.05")).to_integral_value(rounding=ROUND_CEILING))
        factor = Decimal("1.0") + D(bands) * D("0.02")
        return revised, float(pct), True, round4(factor)
    return revised, float(pct), False, 1.0
