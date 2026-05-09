"""Calculation rules from §3 / SCAFFOLD §1.3."""

from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING


# ---- Constants from scaffold ----
REFERENCE_MILEAGE_KM = 200000
MILEAGE_DECAY = 0.5
ACCIDENT_PENALTY_BP = 800
MAJOR_ACCIDENT_EXTRA_BP = 1200
MAINT_PENALTY_BP = 50
DISCREPANCY_PENALTY = 0.15
BASE_PRICE_CENTS = 1_000_000
MILEAGE_DISCREPANCY_TOLERANCE = 0.05

W_GRADE = 0.5
W_MILEAGE = 0.2
W_HISTORY = 0.3

TIER_1_CEILING = 5_000_000     # 50,000.00 currency units
TIER_2_CEILING = 20_000_000    # 200,000.00
INCR_LOW = 50_000
INCR_MID = 200_000
INCR_HIGH = 500_000

LENDER_RULES = {
    "LENDER_A": {"min_credit": 680, "min_down_bp": 1500},
    "LENDER_B": {"min_credit": 640, "min_down_bp": 2000},
    "LENDER_C": {"min_credit": 600, "min_down_bp": 2500},
}

WARRANTY_PACKAGES = {
    "BASIC":    {"months": 6,  "scope": ["POWERTRAIN"],
                 "per_claim_cap": 200000, "total_cap": 500000},
    "STANDARD": {"months": 12, "scope": ["POWERTRAIN", "ELECTRICAL", "COOLING"],
                 "per_claim_cap": 500000, "total_cap": 2000000},
    "PREMIUM":  {"months": 24, "scope": ["POWERTRAIN", "ELECTRICAL", "COOLING",
                                         "INFOTAINMENT", "SUSPENSION", "INTERIOR"],
                 "per_claim_cap": 1500000, "total_cap": 6000000},
}

PARTIAL_BASE_PCT_NO_3P = 0.10
PARTIAL_BASE_PCT_WITH_3P = 0.30
DISCREPANCY_BUMP = 0.10
SELLER_COMPENSATION_PCT = 0.05

BUYER_DEPOSIT_LIMIT_CENTS = 50_000_000

GRADE_VALUES = {"A": 1.0, "B": 0.9, "C": 0.8, "D": 0.6}


# ---- Rounding helpers ----
def round_half_up(x) -> int:
    """Half-up rounding to integer."""
    d = Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(d)


def ceil_int(x) -> int:
    """Ceiling rounding to integer."""
    d = Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_CEILING)
    return int(d)


# ---- Calculations ----

def provisional_price_valuation(declared_mileage_km: int,
                                accident_count: int,
                                maintenance_count: int) -> int:
    base = BASE_PRICE_CENTS
    declared_mileage_km = max(int(declared_mileage_km or 0), 0)
    mileage_factor = max(0.5, 1.0 - (declared_mileage_km / REFERENCE_MILEAGE_KM) * MILEAGE_DECAY)
    history_penalty = (accident_count * ACCIDENT_PENALTY_BP
                       + maintenance_count * MAINT_PENALTY_BP) / 10000.0
    provisional = base * mileage_factor * (1.0 - history_penalty)
    return round_half_up(provisional)


def final_price_valuation(verified_mileage_km: int,
                          exterior_grade: str,
                          interior_grade: str,
                          mechanical_grade: str,
                          accident_count: int,
                          major_accident_count: int,
                          maintenance_count: int,
                          mileage_discrepancy_flag: bool) -> int:
    base = BASE_PRICE_CENTS
    verified_mileage_km = max(int(verified_mileage_km or 0), 0)
    mileage_factor = max(0.5, 1.0 - (verified_mileage_km / REFERENCE_MILEAGE_KM) * MILEAGE_DECAY)
    grade_avg = (GRADE_VALUES[exterior_grade]
                 + GRADE_VALUES[interior_grade]
                 + GRADE_VALUES[mechanical_grade]) / 3.0
    history_penalty = (accident_count * ACCIDENT_PENALTY_BP
                       + major_accident_count * MAJOR_ACCIDENT_EXTRA_BP
                       + maintenance_count * MAINT_PENALTY_BP) / 10000.0
    discrepancy_multiplier = (1.0 - DISCREPANCY_PENALTY) if mileage_discrepancy_flag else 1.0
    final = base * mileage_factor * grade_avg * (1.0 - history_penalty) * discrepancy_multiplier
    return round_half_up(final)


def assessment_score(verified_mileage_km: int,
                     exterior_grade: str,
                     interior_grade: str,
                     mechanical_grade: str,
                     accident_count: int,
                     major_accident_count: int,
                     mileage_discrepancy_flag: bool) -> int:
    grade_pts = ((GRADE_VALUES[exterior_grade]
                  + GRADE_VALUES[interior_grade]
                  + GRADE_VALUES[mechanical_grade]) / 3.0) * 100.0
    mileage_pts = max(0.0, 100.0 - (verified_mileage_km / REFERENCE_MILEAGE_KM) * 100.0)
    history_pts = max(
        0.0,
        100.0
        - accident_count * 10.0
        - major_accident_count * 15.0
        - (20.0 if mileage_discrepancy_flag else 0.0),
    )
    weighted = W_GRADE * grade_pts + W_MILEAGE * mileage_pts + W_HISTORY * history_pts
    score = round_half_up(weighted)
    if score < 0:
        score = 0
    if score > 100:
        score = 100
    return score


def mileage_discrepancy(observed: int, declared: int) -> bool:
    delta = observed - declared
    if delta < 0:
        return True
    if declared > 0 and (abs(delta) / declared) > MILEAGE_DISCREPANCY_TOLERANCE:
        return True
    return False


def bid_increment_for(current_max: int) -> int:
    if current_max < TIER_1_CEILING:
        return INCR_LOW
    if current_max < TIER_2_CEILING:
        return INCR_MID
    return INCR_HIGH


def lender_apr_bp(lender_code: str, credit_score: int):
    """Returns the APR in basis points or None if the loan must be rejected."""
    if lender_code == "LENDER_A":
        if credit_score >= 740:
            return 480
        if credit_score >= 680:
            return 580
        return None
    if lender_code == "LENDER_B":
        if credit_score >= 700:
            return 580
        if credit_score >= 640:
            return 680
        return None
    if lender_code == "LENDER_C":
        if credit_score >= 660:
            return 780
        if credit_score >= 600:
            return 880
        return None
    return None


def loan_amortization(agreed_price_cents: int,
                      requested_principal_cents: int,
                      down_payment_ratio_bp: int,
                      term_months: int,
                      lender_code: str,
                      credit_score: int):
    """Returns (approved_principal_cents, monthly_payment_cents, total_interest_cents).
    Returns None if the loan should be rejected."""
    apr_bp = lender_apr_bp(lender_code, credit_score)
    if apr_bp is None:
        return None

    # max_principal: ceil() on the down-payment portion
    down_payment = ceil_int((agreed_price_cents * down_payment_ratio_bp) / 10000.0)
    max_principal = agreed_price_cents - down_payment
    if max_principal < 0:
        max_principal = 0
    approved_principal = min(requested_principal_cents, max_principal)
    if approved_principal <= 0:
        return (approved_principal, 0, 0)

    # monthly_rate = apr_bp / 10000 / 12, single ceil at the end
    monthly_rate = apr_bp / 10000.0 / 12.0
    n = term_months
    if monthly_rate == 0:
        monthly_payment = ceil_int(approved_principal / n)
    else:
        denom = 1.0 - (1.0 + monthly_rate) ** (-n)
        monthly_payment = ceil_int((approved_principal * monthly_rate) / denom)

    total_interest = monthly_payment * n - approved_principal
    return (approved_principal, monthly_payment, total_interest)


def warranty_claim_payout(package_code: str,
                          claimed_amount_cents: int,
                          running_total_payout_cents: int) -> int:
    pkg = WARRANTY_PACKAGES[package_code]
    per_claim_cap = pkg["per_claim_cap"]
    total_cap = pkg["total_cap"]
    remaining = max(0, total_cap - running_total_payout_cents)
    return min(claimed_amount_cents, per_claim_cap, remaining)


def dispute_compensation(resolution: str,
                         agreed_price_cents: int,
                         had_third_party_report: bool,
                         mileage_discrepancy_at_sale: bool) -> int:
    if resolution == "REFUND_FULL":
        return agreed_price_cents
    if resolution == "REFUND_PARTIAL":
        base_pct = PARTIAL_BASE_PCT_WITH_3P if had_third_party_report else PARTIAL_BASE_PCT_NO_3P
        if mileage_discrepancy_at_sale:
            base_pct += DISCREPANCY_BUMP
        return round_half_up(agreed_price_cents * base_pct)
    if resolution == "COMPENSATE_SELLER":
        return round_half_up(agreed_price_cents * SELLER_COMPENSATION_PCT)
    if resolution == "NO_ACTION":
        return 0
    return 0
