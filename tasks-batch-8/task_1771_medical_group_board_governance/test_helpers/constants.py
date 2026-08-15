"""Domain thresholds and defaults (PRD §2.4, §2.8, §3)."""

# Logical clock startup instant (PRD §2.4).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# GovernancePolicy defaults (PRD §2.8).
POLICY_DEFAULTS = {
    "board_quorum_count": 5,
    "supermajority_num": 2,
    "supermajority_den": 3,
    "voting_window_days": 14,
    "offer_window_days": 30,
    "buy_in_base_shareholder_cents": 25000000,
    "buy_in_base_partner_cents": 10000000,
    "tenure_discount_pct_per_year": 0.02,
    "max_tenure_discount_pct": 0.20,
    "min_buy_in_cents": 5000000,
    "fiscal_year_start_month": 7,
    "late_fee_pct": 0.10,
    "delinquency_grace_days": 30,
    "minority_discount_pct": 0.15,
    "ebitda_multiple": 6,
    "trailing_ebitda_cents": 0,
    "bonus_pool_pct": 0.25,
    "distribution_cap_pct": 0.60,
    "seniority_carve_pct": 0.20,
    "seniority_tier_years": 5,
    "max_dispute_rounds": 2,
    "max_committee_members": 7,
}

# Convenience aliases used across tests.
TOTAL_SHARES_AUTHORIZED = 1_000_000
BUY_IN_BASE_SHAREHOLDER_CENTS = POLICY_DEFAULTS["buy_in_base_shareholder_cents"]
BUY_IN_BASE_PARTNER_CENTS = POLICY_DEFAULTS["buy_in_base_partner_cents"]
MIN_BUY_IN_CENTS = POLICY_DEFAULTS["min_buy_in_cents"]
MAX_COMMITTEE_MEMBERS = POLICY_DEFAULTS["max_committee_members"]
MAX_DISPUTE_ROUNDS = POLICY_DEFAULTS["max_dispute_rounds"]
VOTING_WINDOW_DAYS = POLICY_DEFAULTS["voting_window_days"]
OFFER_WINDOW_DAYS = POLICY_DEFAULTS["offer_window_days"]
LATE_FEE_PCT = POLICY_DEFAULTS["late_fee_pct"]
DELINQUENCY_GRACE_DAYS = POLICY_DEFAULTS["delinquency_grace_days"]
BONUS_POOL_PCT = POLICY_DEFAULTS["bonus_pool_pct"]
DISTRIBUTION_CAP_PCT = POLICY_DEFAULTS["distribution_cap_pct"]
SENIORITY_CARVE_PCT = POLICY_DEFAULTS["seniority_carve_pct"]
SENIORITY_TIER_YEARS = POLICY_DEFAULTS["seniority_tier_years"]
MINORITY_DISCOUNT_PCT = POLICY_DEFAULTS["minority_discount_pct"]
EBITDA_MULTIPLE = POLICY_DEFAULTS["ebitda_multiple"]

# Buy-out payment schedule splits (PRD §3.6): 40% / 30% / 30%.
PAYMENT_SCHEDULE_PCTS = (0.40, 0.30, 0.30)
