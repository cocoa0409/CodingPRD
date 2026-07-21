"""Underwriting + policy/invoice creation logic shared by submit-underwriting and decide (PRD §3.2-3.3)."""
from datetime import timedelta
from db import new_common_fields, fmt_ts, parse_ts, add_months
from services import calculations as calc


def score_enrollment(enrollment, property_):
    self_score, self_tier = calc.underwriting_risk_score(
        enrollment["self_reported_annual_income_cents"],
        property_["monthly_rent_cents"],
        enrollment["credit_proxy_score"],
        enrollment["prior_eviction_count"],
    )
    verified_score = None
    verified_tier = None
    if enrollment["employment_verified"] and enrollment["verified_annual_income_cents"] is not None:
        verified_score, verified_tier = calc.underwriting_risk_score(
            enrollment["verified_annual_income_cents"],
            property_["monthly_rent_cents"],
            enrollment["credit_proxy_score"],
            enrollment["prior_eviction_count"],
        )
    official_score = verified_score if verified_score is not None else self_score
    official_tier = verified_tier if verified_score is not None else self_tier
    return {
        "risk_score_self_reported": self_score,
        "risk_score_verified": verified_score,
        "risk_tier": official_tier,
        "official_score": official_score,
    }


def compute_fee(coverage_limit_cents, risk_tier, property_, rule):
    return calc.monthly_fee_calculation(
        coverage_limit_cents, risk_tier, property_["monthly_rent_cents"], rule["max_monthly_fee_pct_of_rent"]
    )


def create_policy_and_first_invoice(enrollment, monthly_fee_cents):
    lease_start = parse_ts(enrollment["lease_start_date"])
    policy = {
        **new_common_fields(),
        "renter_enrollment_id": enrollment["id"],
        "coverage_limit_cents": enrollment["requested_coverage_limit_cents"],
        "payment_plan": enrollment["payment_plan"],
        "monthly_fee_cents": monthly_fee_cents,
        "gross_available_coverage_cents": enrollment["requested_coverage_limit_cents"],
        "net_available_coverage_cents": enrollment["requested_coverage_limit_cents"],
        "lease_start_date": enrollment["lease_start_date"],
        "lease_end_date": enrollment["lease_end_date"],
        "status": "AWAITING_FIRST_PAYMENT",
        "cancelled_at": None,
    }

    billing_period_start = lease_start
    billing_period_end = add_months(lease_start, 1)
    due_date = billing_period_start + timedelta(days=10)
    allocation = calc.premium_installment_allocation(monthly_fee_cents)

    invoice = {
        **new_common_fields(),
        "policy_id": policy["id"],
        "billing_period_start": fmt_ts(billing_period_start),
        "billing_period_end": fmt_ts(billing_period_end),
        "amount_cents": allocation["amount_cents"],
        "insurance_premium_cents": allocation["insurance_premium_cents"],
        "platform_fee_cents": allocation["platform_fee_cents"],
        "state_tax_cents": allocation["state_tax_cents"],
        "due_date": fmt_ts(due_date),
        "status": "ISSUED",
        "paid_at": None,
    }
    return policy, invoice


def leases_overlap(existing_policies, new_start, new_end):
    NON_TERMINAL = {"AWAITING_FIRST_PAYMENT", "ACTIVE", "LAPSED"}
    for p in existing_policies:
        if p["status"] not in NON_TERMINAL:
            continue
        p_start = parse_ts(p["lease_start_date"])
        p_end = parse_ts(p["lease_end_date"])
        if new_start < p_end and p_start < new_end:
            return True
    return False
