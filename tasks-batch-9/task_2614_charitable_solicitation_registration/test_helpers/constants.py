"""Domain thresholds and pinned constants drawn from the PRD's calculations."""

from typing import Dict

# The logical clock reads exactly this instant until an administrator moves it.
INITIAL_CLOCK = "2026-08-01T00:00:00Z"

THRESHOLDS: Dict[str, float] = {
    # Filing-fee tier boundaries on the supporting statement's contributions_cents.
    "FEE_TIER_1_MAX_CENTS": 2_500_000,
    "FEE_TIER_2_MAX_CENTS": 10_000_000,
    "FEE_TIER_3_MAX_CENTS": 50_000_000,
    "TIER_1_BASE_CENTS": 2_500,
    "TIER_2_BASE_CENTS": 5_000,
    "TIER_3_BASE_CENTS": 15_000,
    "TIER_4_BASE_CENTS": 40_000,
    # An initial filing costs half again what a renewal costs.
    "INITIAL_FILING_MULTIPLIER": 1.5,
    # Late-penalty accrual.
    "DAYS_PER_ACCRUAL_MONTH": 30,
    # Remediation settlement discount tiers, keyed on the penalty subtotal.
    "DISCOUNT_TIER_2_MIN_CENTS": 20_000,
    "DISCOUNT_TIER_2_PCT": 0.10,
    "DISCOUNT_TIER_3_MIN_CENTS": 50_000,
    "DISCOUNT_TIER_3_PCT": 0.20,
    # Extension grant length under the federal-return basis.
    "IRS_990_EXTENSION_DAYS": 180,
    # Contract filing grace beyond filing_due_date.
    "CONTRACT_FILING_HARD_STOP_DAYS": 60,
    "LATE_CONTRACT_SURCHARGE_CENTS": 10_000,
    # Pagination.
    "PAGINATION_DEFAULT_LIMIT": 10,
    "PAGINATION_MIN_LIMIT": 1,
    "PAGINATION_MAX_LIMIT": 100,
}

# Documented state-profile defaults for every field that is not one of the six
# required on creation.
STATE_PROFILE_DEFAULTS: Dict[str, object] = {
    "donor_count_trigger": 25,
    "contribution_trigger_cents": 2_500_000,
    "online_presence_counts": False,
    "extension_allowed": False,
    "extension_max_days": 0,
    "disclosure_required_clauses": [],
    "fundraiser_contract_filing_days": 10,
    "fundraiser_bond_minimum_cents": 0,
    "coventure_filing_required": False,
    "coventure_buffer_days": 0,
    "base_filing_fee_cents": 2_500,
    "online_surcharge_cents": 0,
    "per_contract_fee_cents": 0,
    "filing_fee_cap_cents": 30_000,
    "late_fee_base_cents": 2_000,
    "late_fee_escalation_pct": 0.1,
    "late_fee_cap_cents": 50_000,
    "cure_period_days": 30,
    "reinstatement_fee_cents": 12_500,
}

TEST_DEFAULTS: Dict[str, object] = {
    "ORGANIZATION_LEGAL_NAME": "Harbor Light Foundation",
    "ORGANIZATION_EIN": "123456789",
    "FISCAL_YEAR": 2026,
    "FISCAL_YEAR_END_MONTH": 6,
    "TOTAL_REVENUE_CENTS": 26_000_000,
    "CONTRIBUTIONS_CENTS": 20_000_000,
    "PROGRAM_EXPENSE_CENTS": 18_000_000,
    "FUNDRAISING_EXPENSE_CENTS": 4_000_000,
    "MANAGEMENT_EXPENSE_CENTS": 2_000_000,
}
