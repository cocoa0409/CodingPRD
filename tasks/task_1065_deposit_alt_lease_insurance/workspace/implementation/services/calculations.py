"""All `calculations` from SCAFFOLD.yaml / PRD §3, implemented with Decimal precision."""
from decimal import Decimal
from utils import D, round_half_up, floor_to_int, clamp

# --- underwriting_risk_score (PRD §3.2) ---
W_INCOME = D("0.4")
W_CREDIT = D("0.4")
W_EVICTION = D("0.2")
TARGET_INCOME_RATIO = D("3.0")
AUTO_APPROVE_THRESHOLD = 35
LOW_TIER_MAX = 20
MEDIUM_TIER_MAX = 50


def risk_tier_for_score(score):
    if score <= LOW_TIER_MAX:
        return "LOW"
    if score <= MEDIUM_TIER_MAX:
        return "MEDIUM"
    return "HIGH"


def underwriting_risk_score(annual_income_cents, monthly_rent_cents, credit_proxy_score, prior_eviction_count):
    income_to_rent_ratio = D(annual_income_cents) / (D(monthly_rent_cents) * 12)
    income_risk = clamp(D(0), D(100), D(100) - (income_to_rent_ratio / TARGET_INCOME_RATIO) * 100)
    credit_risk = clamp(D(0), D(100), (D(850) - D(credit_proxy_score)) / D(850 - 300) * 100)
    eviction_risk = min(D(100), D(prior_eviction_count) * 40)
    blended = W_INCOME * income_risk + W_CREDIT * credit_risk + W_EVICTION * eviction_risk
    score = round_half_up(blended)
    return score, risk_tier_for_score(score)


# --- policy_available_coverage (PRD §2.8) ---
def policy_gross_available_coverage(coverage_limit_cents, claims):
    reserved = sum(
        c["approved_amount_cents"] or 0
        for c in claims
        if c["status"] in ("APPROVED", "CLOSED")
    )
    return coverage_limit_cents - reserved


def policy_net_available_coverage(coverage_limit_cents, payouts):
    disbursed = sum(p["amount_cents"] for p in payouts if p["status"] == "DISBURSED")
    return coverage_limit_cents - disbursed


# --- monthly_fee_calculation (PRD §3.3) ---
BASE_RATE_PCT = D("0.008")
FLAT_ADMIN_FEE_CENTS = 150
MIN_FEE_CENTS = 1500
RISK_MULTIPLIER = {"LOW": D("1.0"), "MEDIUM": D("1.3"), "HIGH": D("1.6")}


def monthly_fee_calculation(coverage_limit_cents, risk_tier, monthly_rent_cents, max_monthly_fee_pct_of_rent):
    risk_multiplier = RISK_MULTIPLIER[risk_tier]
    pre_clamp_cents = round_half_up(BASE_RATE_PCT * D(coverage_limit_cents) * risk_multiplier) + FLAT_ADMIN_FEE_CENTS
    state_cap_cents = floor_to_int(D(monthly_rent_cents) * D(max_monthly_fee_pct_of_rent))
    exceeds_cap = pre_clamp_cents > state_cap_cents
    monthly_fee_cents = None if exceeds_cap else max(MIN_FEE_CENTS, pre_clamp_cents)
    return {
        "pre_clamp_cents": pre_clamp_cents,
        "state_cap_cents": state_cap_cents,
        "exceeds_cap": exceeds_cap,
        "monthly_fee_cents": monthly_fee_cents,
    }


# --- premium_installment_allocation (PRD §3.3) ---
INSURANCE_PREMIUM_PCT = D("0.85")
PLATFORM_FEE_PCT = D("0.10")
STATE_TAX_PCT = D("0.05")


def premium_installment_allocation(monthly_fee_cents):
    insurance_premium_cents = round_half_up(D(monthly_fee_cents) * INSURANCE_PREMIUM_PCT)
    platform_fee_cents = round_half_up(D(monthly_fee_cents) * PLATFORM_FEE_PCT)
    state_tax_cents = round_half_up(D(monthly_fee_cents) * STATE_TAX_PCT)
    amount_cents = insurance_premium_cents + platform_fee_cents + state_tax_cents
    return {
        "insurance_premium_cents": insurance_premium_cents,
        "platform_fee_cents": platform_fee_cents,
        "state_tax_cents": state_tax_cents,
        "amount_cents": amount_cents,
    }


# --- claim_payout_calculation (PRD §3.5) ---
FLAT_DEDUCTIBLE_CENTS = 5000
HIGH_TIER_THRESHOLD_CENTS = 200000
HIGH_TIER_DEDUCTIBLE_MULTIPLIER = D("1.5")


def claim_payout_calculation(total_claimed_amount_cents, gross_available_coverage_cents):
    provisional_payout_cents = max(
        0, min(total_claimed_amount_cents, gross_available_coverage_cents) - FLAT_DEDUCTIBLE_CENTS
    )
    if provisional_payout_cents >= HIGH_TIER_THRESHOLD_CENTS:
        deductible_cents = int(D(FLAT_DEDUCTIBLE_CENTS) * HIGH_TIER_DEDUCTIBLE_MULTIPLIER)
    else:
        deductible_cents = FLAT_DEDUCTIBLE_CENTS
    # The payout the claim would generate, before the gross-coverage cap (PRD §3.5): apply the
    # step-two deductible to the total claimed amount directly, floored at zero. This uncapped
    # figure is what the ERR_COVERAGE_LIMIT_EXCEEDED gate compares against gross coverage.
    uncapped_amount_cents = max(0, total_claimed_amount_cents - deductible_cents)
    approved_amount_cents = min(uncapped_amount_cents, gross_available_coverage_cents)
    return {
        "approved_amount_cents": approved_amount_cents,
        "uncapped_amount_cents": uncapped_amount_cents,
        "deductible_cents": deductible_cents,
    }


# --- subrogation_outstanding_balance (PRD §3.7) ---
def subrogation_outstanding_balance(original_demand_amount_cents, recovery_payments):
    paid = sum(p["amount_cents"] for p in recovery_payments if p["status"] == "SUCCEEDED")
    return original_demand_amount_cents - paid


# --- property_total_paid_claims (PRD §2.9) ---
def property_total_paid_claims(payouts):
    return sum(p["amount_cents"] for p in payouts if p["status"] == "DISBURSED")
